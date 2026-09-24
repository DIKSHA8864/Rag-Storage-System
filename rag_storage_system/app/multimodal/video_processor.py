"""
Video processing for Client intake - two independent extractions, each
producing its own ExtractedContent item(s):

1. Audio track -> transcript, the same way a standalone audio file is
   transcribed (app/multimodal/audio_processor.py), via the same
   pluggable STT provider, called directly on the video file's raw
   bytes. With STT_PROVIDER=whisper (app/multimodal/speech_to_text.py's
   WhisperSTTProvider), this is real: faster-whisper demuxes the
   video's audio stream itself (via PyAV/ffmpeg) and transcribes it, no
   separate step needed here. With the default "mock" provider, this
   is still just a clearly labeled placeholder (is_mock=True).

2. Visual content -> up to VIDEO_FRAME_SAMPLE_COUNT (config/settings.py,
   default 3) representative frames, sampled at evenly-spaced
   timestamps across the video's duration via PyAV (no ffmpeg
   subprocess needed - the same library already bundled for #1), each
   captioned through the same pluggable Vision provider
   app/multimodal/image_processor.py already uses for standalone
   images (app/multimodal/vision.py). Set VIDEO_FRAME_SAMPLE_COUNT=0 to
   skip this (e.g. to avoid per-frame cost with a paid Vision
   provider) and keep audio-only behavior.

A frame that fails to decode, or fails to caption, is skipped rather
than failing the whole video - a partial or empty set of frame
captions is preferable to losing an already-successful transcript over
what is, relative to the transcript, a secondary enrichment.
"""

import io
import logging
import tempfile
from pathlib import Path

import av

from app.multimodal.models import ExtractedContent
from app.multimodal.speech_to_text import get_stt_provider
from app.multimodal.vision import get_vision_provider
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _sample_frame_pngs(video_path: Path, count: int) -> list[tuple[float, bytes]]:
    """
    Returns up to `count` (timestamp_seconds, PNG bytes) pairs, evenly
    spaced across the video's duration (excluding the very start/end,
    where an intake video is often still framing the shot or just
    ending). Returns fewer than `count` (or none at all) rather than
    raising, if the video is too short, has no video stream at all
    (e.g. a video container holding audio-only content), or a
    particular timestamp's frame can't be decoded.
    """

    if count <= 0:
        return []

    try:
        container = av.open(str(video_path))
    except Exception as exc:
        logger.warning("Could not open '%s' for frame sampling: %s", video_path, exc)
        return []

    try:
        video_stream = next((s for s in container.streams if s.type == "video"), None)
        if video_stream is None or not container.duration:
            return []

        duration_seconds = container.duration / av.time_base
        timestamps = [duration_seconds * (i + 1) / (count + 1) for i in range(count)]

        frames: list[tuple[float, bytes]] = []
        for target in timestamps:
            try:
                offset = int(target / video_stream.time_base)
                # backward=True (the default) seeks to the nearest keyframe
                # AT OR BEFORE `offset` - decoding must then continue
                # forward from there until a frame actually at/past the
                # target timestamp is reached; the seek alone only
                # repositions the read pointer, it does not land on an
                # arbitrary timestamp itself.
                container.seek(offset, stream=video_stream)

                for frame in container.decode(video_stream):
                    pts_time = float(frame.pts * video_stream.time_base) if frame.pts is not None else 0.0
                    if pts_time >= target:
                        buffer = io.BytesIO()
                        frame.to_image().save(buffer, format="PNG")
                        frames.append((pts_time, buffer.getvalue()))
                        break
            except Exception as exc:
                logger.warning("Could not decode a frame near %.1fs in '%s': %s", target, video_path, exc)
                continue

        return frames
    finally:
        container.close()


def process_video(filename: str, data: bytes) -> list[ExtractedContent]:
    stt_provider = get_stt_provider()
    transcript, transcript_is_mock = stt_provider.transcribe(data, filename)

    results = [
        ExtractedContent(
            content_type="transcript", text=transcript, provider=stt_provider.name, is_mock=transcript_is_mock
        )
    ]

    frame_sample_count = get_settings().video_frame_sample_count
    if frame_sample_count <= 0:
        return results

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".mp4", delete=False) as tmp_file:
        tmp_file.write(data)
        tmp_path = Path(tmp_file.name)

    try:
        vision_provider = get_vision_provider()

        for timestamp, frame_png_bytes in _sample_frame_pngs(tmp_path, frame_sample_count):
            frame_label = f"{filename} @ {timestamp:.1f}s.png"

            try:
                caption, caption_is_mock = vision_provider.describe(frame_png_bytes, frame_label)
            except Exception as exc:
                logger.warning("Could not caption the frame at %.1fs of '%s': %s", timestamp, filename, exc)
                continue

            results.append(
                ExtractedContent(
                    content_type="frame_caption",
                    text=f"[{timestamp:.1f}s] {caption}",
                    provider=vision_provider.name,
                    is_mock=caption_is_mock,
                )
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    return results

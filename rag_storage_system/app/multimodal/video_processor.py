"""
Video processing for Client intake - treats a video's audio track the
same way a standalone audio file is transcribed
(app/multimodal/audio_processor.py), via the same pluggable STT
provider, called directly on the video file's raw bytes. With
STT_PROVIDER=whisper (app/multimodal/speech_to_text.py's
WhisperSTTProvider), this is real: faster-whisper demuxes the video's
audio stream itself (via PyAV/ffmpeg) and transcribes it, no separate
step needed here. With the default "mock" provider, this is still just
a clearly labeled placeholder (is_mock=True).

Video's VISUAL content (frames) is not analyzed - only its audio track
is transcribed. Extracting and captioning representative frames
through app/multimodal/vision.py would be a further extension, not yet
built.
"""

from app.multimodal.models import ExtractedContent
from app.multimodal.speech_to_text import get_stt_provider


def process_video(filename: str, data: bytes) -> ExtractedContent:
    provider = get_stt_provider()
    transcript, is_mock = provider.transcribe(data, filename)

    return ExtractedContent(content_type="transcript", text=transcript, provider=provider.name, is_mock=is_mock)

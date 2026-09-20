"""
Video processing for Client intake - Phase 3 foundation treats a
video's audio track the same way a standalone audio file is
transcribed (app/multimodal/audio_processor.py), via the same
pluggable STT provider. No real video/audio demuxing is wired in yet
(this sandbox has no ffmpeg installed) - the configured STT provider is
called directly on the video file's raw bytes, which is exactly as
accurate as a placeholder needs to be, and clearly labeled as such
(is_mock=True) either way. A real provider implementation is free to
demux the video itself before transcribing.
"""

from app.multimodal.models import ExtractedContent
from app.multimodal.speech_to_text import get_stt_provider


def process_video(filename: str, data: bytes) -> ExtractedContent:
    provider = get_stt_provider()
    transcript, is_mock = provider.transcribe(data, filename)

    return ExtractedContent(content_type="transcript", text=transcript, provider=provider.name, is_mock=is_mock)

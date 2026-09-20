"""Audio processing for Client intake - transcribes via the configured STT provider (app/multimodal/speech_to_text.py)."""

from app.multimodal.models import ExtractedContent
from app.multimodal.speech_to_text import get_stt_provider


def process_audio(filename: str, data: bytes) -> ExtractedContent:
    provider = get_stt_provider()
    transcript, is_mock = provider.transcribe(data, filename)

    return ExtractedContent(content_type="transcript", text=transcript, provider=provider.name, is_mock=is_mock)

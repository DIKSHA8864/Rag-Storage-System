"""
Speech-to-text provider interface - transcribes an audio file (or an
audio track pulled from video). Pluggable, same pattern as
app/multimodal/ocr.py: get_stt_provider() reads STT_PROVIDER
(config/settings.py). "mock" (default) needs no external service or
API key - this sandbox has no whisper/ffmpeg installed.
"""

from abc import ABC, abstractmethod

from config.settings import get_settings


class STTProvider(ABC):
    """Abstract base class for all speech-to-text providers."""

    name: str

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, filename: str) -> tuple[str, bool]:
        """Returns (transcript, is_mock) - see OCRProvider.extract_text()'s docstring for what is_mock guards."""

        raise NotImplementedError


class MockSTTProvider(STTProvider):
    """Free, offline default - see MockOCRProvider's docstring for the same rationale."""

    name = "mock"

    def transcribe(self, audio_bytes: bytes, filename: str) -> tuple[str, bool]:
        return (
            f"[MOCK TRANSCRIPT] No speech-to-text engine is configured. "
            f"'{filename}' ({len(audio_bytes)} bytes) was received but "
            "not transcribed - attorney review required.",
            True,
        )


def get_stt_provider() -> STTProvider:
    provider = get_settings().stt_provider

    if provider == "mock":
        return MockSTTProvider()

    raise RuntimeError(f"Unknown STT_PROVIDER: {provider!r}")

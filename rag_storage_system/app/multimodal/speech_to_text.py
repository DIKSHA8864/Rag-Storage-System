"""
Speech-to-text provider interface - transcribes an audio file (or an
audio track pulled from video). Pluggable, same pattern as
app/multimodal/ocr.py: get_stt_provider() reads STT_PROVIDER
(config/settings.py). "mock" (default) needs no external service or
API key; "whisper" (see WhisperSTTProvider below) is a real, free,
local implementation (faster-whisper) - no API key, no network call at
request time once its model is cached.
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


class WhisperSTTProvider(STTProvider):
    """
    Real speech-to-text via a local Whisper model (faster-whisper) -
    free, no API key. faster-whisper decodes its input with PyAV
    (bundled ffmpeg libraries), which demuxes an audio stream out of
    ANY container it's given - so this same class transcribes a plain
    audio file (mp3/wav/m4a) or a video file (mp4/mov/avi) identically;
    app/multimodal/video_processor.py calls this exact provider on a
    video's raw bytes with no separate demuxing step, exactly as its
    own docstring anticipated.

    The model is loaded once per process (first call) and reused - see
    WHISPER_MODEL_SIZE/WHISPER_DEVICE/WHISPER_COMPUTE_TYPE
    (config/settings.py). Loading it downloads and caches the chosen
    model from Hugging Face on first use (~75MB for the default "base"
    size) - `_load_model` is a separate method precisely so tests can
    monkeypatch it instead of requiring that download.
    """

    name = "whisper"

    _model = None  # process-wide cache - one loaded model, not one per instance/request

    def __init__(self):
        settings = get_settings()
        self._model_size = settings.whisper_model_size
        self._device = settings.whisper_device
        self._compute_type = settings.whisper_compute_type

    def _load_model(self):
        if WhisperSTTProvider._model is None:
            from faster_whisper import WhisperModel

            WhisperSTTProvider._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type
            )
        return WhisperSTTProvider._model

    def transcribe(self, audio_bytes: bytes, filename: str) -> tuple[str, bool]:
        import tempfile
        from pathlib import Path

        suffix = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = Path(tmp_file.name)

        try:
            model = self._load_model()
            segments, _info = model.transcribe(str(tmp_path))
            transcript = " ".join(segment.text.strip() for segment in segments)
        except Exception as exc:
            raise RuntimeError(f"Whisper transcription failed for '{filename}': {exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        return transcript.strip(), False


def get_stt_provider() -> STTProvider:
    provider = get_settings().stt_provider

    if provider == "mock":
        return MockSTTProvider()
    if provider == "whisper":
        return WhisperSTTProvider()

    raise RuntimeError(f"Unknown STT_PROVIDER: {provider!r}")

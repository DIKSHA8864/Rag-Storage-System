"""
Vision provider interface - describes the visual content of an image
that OCR alone doesn't capture (a photo of a scene, a diagram) as a
short caption. Pluggable, same pattern as app/multimodal/ocr.py.
"""

from abc import ABC, abstractmethod

from config.settings import get_settings


class VisionProvider(ABC):
    """Abstract base class for all vision/captioning providers."""

    name: str

    @abstractmethod
    def describe(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        """Returns (caption, is_mock) - see OCRProvider.extract_text()'s docstring for what is_mock guards."""

        raise NotImplementedError


class MockVisionProvider(VisionProvider):
    """Free, offline default - see MockOCRProvider's docstring for the same rationale."""

    name = "mock"

    def describe(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        return (
            f"[MOCK CAPTION] No vision engine is configured. "
            f"'{filename}' ({len(image_bytes)} bytes) was received but "
            "not described - attorney review required.",
            True,
        )


def get_vision_provider() -> VisionProvider:
    provider = get_settings().vision_provider

    if provider == "mock":
        return MockVisionProvider()

    raise RuntimeError(f"Unknown VISION_PROVIDER: {provider!r}")

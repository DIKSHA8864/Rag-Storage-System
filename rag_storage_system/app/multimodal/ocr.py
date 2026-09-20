"""
OCR provider interface - pulls text out of an image (a scanned page, a
photographed document). Pluggable so this never hard-codes to one AI
vendor: get_ocr_provider() reads OCR_PROVIDER (config/settings.py) and
returns whichever implementation is configured. "mock" (default) needs
no external service - this sandbox has no OCR engine installed (no
pytesseract, no cloud vision API key).
"""

from abc import ABC, abstractmethod

from config.settings import get_settings


class OCRProvider(ABC):
    """Abstract base class for all OCR providers."""

    name: str

    @abstractmethod
    def extract_text(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        """
        Returns (text, is_mock). `is_mock` must be True whenever the
        returned text is a placeholder rather than a genuine reading of
        the image - app/report/ uses this to flag the source as
        requiring attorney review rather than presenting mock output as
        a real extraction.
        """

        raise NotImplementedError


class MockOCRProvider(OCRProvider):
    """
    Free, offline default. Returns a clearly labeled placeholder
    instead of fabricating plausible-looking text, so a report built
    from it can never be mistaken for a real extraction. Swap in a real
    implementation (pytesseract, a hosted OCR API) by adding a class
    here and pointing OCR_PROVIDER at it.
    """

    name = "mock"

    def extract_text(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        return (
            f"[MOCK OCR] No OCR engine is configured. '{filename}' "
            f"({len(image_bytes)} bytes) was received but its text "
            "content was not extracted - attorney review required.",
            True,
        )


def get_ocr_provider() -> OCRProvider:
    provider = get_settings().ocr_provider

    if provider == "mock":
        return MockOCRProvider()

    raise RuntimeError(f"Unknown OCR_PROVIDER: {provider!r}")

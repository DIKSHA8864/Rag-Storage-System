"""
OCR provider interface - pulls text out of an image (a scanned page, a
photographed document). Pluggable so this never hard-codes to one AI
vendor: get_ocr_provider() reads OCR_PROVIDER (config/settings.py) and
returns whichever implementation is configured. "mock" (default) needs
no external service; "tesseract" (see TesseractOCRProvider below) is a
real, free, local implementation - no API key, no network call at
request time, just the `tesseract-ocr` system package.
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


class TesseractOCRProvider(OCRProvider):
    """
    Real OCR via the local Tesseract engine (the `pytesseract` binding).
    Free, no API key, no network call at request time - only the
    `tesseract-ocr` system package needs to be installed wherever this
    runs (`apt-get install tesseract-ocr` / `brew install tesseract`;
    see README's Setup section). Raises on a genuinely unreadable
    image (corrupt bytes, unsupported format) rather than returning a
    placeholder - app/multimodal/pipeline.py already treats any
    processor exception as that file's processing failure, exactly
    like a corrupt PDF/DOCX already does in document_processor.py.
    """

    name = "tesseract"

    def extract_text(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        import io

        import pytesseract
        from PIL import Image

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                text = pytesseract.image_to_string(image)
        except Exception as exc:
            raise RuntimeError(f"Tesseract OCR failed for '{filename}': {exc}") from exc

        return text.strip(), False


def get_ocr_provider() -> OCRProvider:
    provider = get_settings().ocr_provider

    if provider == "mock":
        return MockOCRProvider()
    if provider == "tesseract":
        return TesseractOCRProvider()

    raise RuntimeError(f"Unknown OCR_PROVIDER: {provider!r}")

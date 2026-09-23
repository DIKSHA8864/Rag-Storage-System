from pathlib import Path

import pymupdf

from app.multimodal.ocr import get_ocr_provider

# Deliberately low: library files are short by design (single-line
# section headers, brief clauses are legitimate real content), so this
# only needs to catch genuinely empty/near-empty pages - the signature
# of a scanned image with no extractable text layer at all - not just
# "short."
_MIN_CHARACTERS_PER_PAGE = 10


def extract_pdf(file_path: Path) -> dict:
    """
    Extract text from a PDF while preserving page boundaries. Normal
    text extraction (pymupdf) is always tried first; a page whose
    extracted text falls below _MIN_CHARACTERS_PER_PAGE - the signature
    of a scanned page with no real text layer - is re-processed through
    the same pluggable OCR provider app/multimodal/ uses for Client
    uploads (app/multimodal/ocr.py's get_ocr_provider()), not a second
    OCR integration.

    Returns a structured dictionary containing:
    - filename
    - file type
    - page count
    - pages (each with an "ocr_used"/"ocr_is_mock" flag when OCR ran)
    - ocr_pages_used: how many pages needed the OCR fallback
    """

    if not file_path.exists():
        raise FileNotFoundError(
            f"PDF file does not exist: {file_path}"
        )

    if file_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a PDF file, got: {file_path.suffix}"
        )

    pages = []
    ocr_pages_used = 0
    ocr_provider = None

    with pymupdf.open(file_path) as document:

        for page_index, page in enumerate(document):

            text = page.get_text("text").strip()
            ocr_used = False
            ocr_is_mock = False

            if len(text) < _MIN_CHARACTERS_PER_PAGE:
                if ocr_provider is None:
                    ocr_provider = get_ocr_provider()

                image_bytes = page.get_pixmap().tobytes("png")
                ocr_text, ocr_is_mock = ocr_provider.extract_text(
                    image_bytes, f"{file_path.name} (page {page_index + 1})"
                )
                text = ocr_text.strip()
                ocr_used = True
                ocr_pages_used += 1

            page_entry = {
                "page_number": page_index + 1,
                "text": text,
                "character_count": len(text),
            }
            if ocr_used:
                page_entry["ocr_used"] = True
                page_entry["ocr_is_mock"] = ocr_is_mock

            pages.append(page_entry)

        page_count = len(document)

    return {
        "filename": file_path.name,
        "file_type": "pdf",
        "page_count": page_count,
        "pages": pages,
        "ocr_pages_used": ocr_pages_used,
    }
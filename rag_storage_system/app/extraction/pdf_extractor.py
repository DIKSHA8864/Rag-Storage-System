from pathlib import Path

import pymupdf


def extract_pdf(file_path: Path) -> dict:
    """
    Extract text from a PDF while preserving page boundaries.

    Returns a structured dictionary containing:
    - filename
    - file type
    - page count
    - pages
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

    with pymupdf.open(file_path) as document:

        for page_index, page in enumerate(document):

            text = page.get_text("text")

            pages.append(
                {
                    "page_number": page_index + 1,
                    "text": text.strip(),
                    "character_count": len(text.strip()),
                }
            )

        page_count = len(document)

    return {
        "filename": file_path.name,
        "file_type": "pdf",
        "page_count": page_count,
        "pages": pages,
    }
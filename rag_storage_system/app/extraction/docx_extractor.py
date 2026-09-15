from pathlib import Path

from docx import Document


def extract_docx(file_path: Path) -> dict:
    """
    Extract text from a DOCX document.

    DOCX does not provide reliable page boundaries through
    python-docx, so we preserve paragraph order instead.
    """

    if not file_path.exists():
        raise FileNotFoundError(
            f"DOCX file does not exist: {file_path}"
        )

    if file_path.suffix.lower() != ".docx":
        raise ValueError(
            f"Expected a DOCX file, got: {file_path.suffix}"
        )

    document = Document(file_path)

    paragraphs = []

    for index, paragraph in enumerate(document.paragraphs):

        text = paragraph.text.strip()

        if not text:
            continue

        paragraphs.append(
            {
                "paragraph_number": index + 1,
                "text": text,
                "style": paragraph.style.name
                if paragraph.style
                else None,
            }
        )

    # DOCX has no real page concept (python-docx does not expose
    # print page breaks), so each paragraph is treated as one
    # synthetic "page". This keeps the extraction output shape
    # consistent with the PDF extractor's {page_number, text} pages
    # list, which is what segmentation relies on - and since a
    # heading is normally its own paragraph, section boundaries
    # still land on their own "page" the same way a PDF heading
    # lands on its own printed page.
    pages = [
        {
            "page_number": paragraph["paragraph_number"],
            "text": paragraph["text"],
        }
        for paragraph in paragraphs
    ]

    return {
        "filename": file_path.name,
        "file_type": "docx",
        "page_count": len(pages),
        "pages": pages,
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
    }
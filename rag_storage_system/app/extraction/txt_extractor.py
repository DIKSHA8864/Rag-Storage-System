import re
from pathlib import Path


# A TXT file has no page concept, but it usually does preserve real
# blank-line paragraph breaks (unlike PDF text extraction). Blank
# lines are used to split the file into synthetic "pages" so
# segmentation has boundaries to work with instead of one giant blob.
_BLANK_LINE = re.compile(r"\n\s*\n")


def extract_txt(file_path: Path) -> dict:
    """
    Extract text from a TXT file while preserving lines.
    """

    if not file_path.exists():
        raise FileNotFoundError(
            f"TXT file does not exist: {file_path}"
        )

    if file_path.suffix.lower() != ".txt":
        raise ValueError(
            f"Expected a TXT file, got: {file_path.suffix}"
        )

    text = file_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    lines = text.splitlines()

    pages = []

    for block in _BLANK_LINE.split(text):

        block_text = block.strip()

        if not block_text:
            continue

        pages.append(
            {
                "page_number": len(pages) + 1,
                "text": block_text,
            }
        )

    # No blank-line breaks at all: treat the whole file as one page.
    if not pages and text.strip():
        pages.append(
            {
                "page_number": 1,
                "text": text.strip(),
            }
        )

    return {
        "filename": file_path.name,
        "file_type": "txt",
        "character_count": len(text),
        "line_count": len(lines),
        "page_count": len(pages),
        "pages": pages,
        "text": text,
        "lines": lines,
    }
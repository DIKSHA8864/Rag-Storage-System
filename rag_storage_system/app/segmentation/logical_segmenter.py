
from pathlib import Path

from app.segmentation.models import LogicalSegment, StructuralElement
from app.segmentation.structure_detector import detect_structure


def _get_document_id(filename: str) -> str:
    return Path(filename).stem


def _find_title_section(pages: list[dict]) -> str | None:
    """
    Find the section title from the first page.

    Example:
        1.1. Background
        1.2. Plaintiffs' Evaluation of Claims
        1.3. Defendants' Evaluation of Claims
    """
    if not pages:
        return None

    first_page_text = pages[0].get("text", "")

    for line in first_page_text.splitlines():
        line = line.strip()

        if not line:
            continue

        parts = line.split()

        if parts and any(char.isdigit() for char in parts[0]) and "." in parts[0]:
            return line

    return None


def _is_title_page(page: dict) -> bool:
    """
    Determine whether a page is primarily a document title/header page.

    For the current documents, page 1 contains:
        CHAPTER 1: INTRODUCTION
        1.x. Section Title
        page number

    We do NOT want this title-page material inside the logical
    content segment.

    This function does NOT use a fixed page-count rule.
    It only checks the actual structure of the page.
    """
    page_number = page.get("page_number")
    text = page.get("text", "").strip()

    if page_number != 1 or not text:
        return False

    structures = detect_structure(text, page_number)

    has_chapter = any(
        item.element_type == "chapter"
        for item in structures
    )

    has_section = any(
        item.element_type == "section"
        for item in structures
    )

    # A first page containing both chapter + numbered section
    # is treated as title/header material.
    return has_chapter and has_section


def segment_document(document: dict) -> list[LogicalSegment]:
    """
    Convert one extracted document into logical segments.

    Important:
    - No page-count limit.
    - No artificial 40-page rule.
    - Pages remain the source boundary.
    - Documents are never merged together.
    - Title/header page is excluded when it is clearly a title page.
    - Actual content is preserved.
    """

    filename = document["filename"]
    # Set by app/extraction/extractor_manager.py (unique per storage path);
    # the bare stem only for an extracted.json written before that existed.
    document_id = document.get("document_id") or _get_document_id(filename)

    pages = document.get("pages", [])

    if not pages:
        return []

    document_section = _find_title_section(pages)

    segments = []

    current_start_page = None
    current_chapter = None
    current_section = document_section
    current_subsection = None

    current_text = []
    current_structures = []

    segment_number = 1

    def flush(end_page: int):
        nonlocal current_start_page
        nonlocal current_text
        nonlocal current_structures
        nonlocal segment_number

        if current_start_page is None:
            return

        text = "\n".join(current_text).strip()

        if not text:
            return

        segment = LogicalSegment(
            segment_id=f"{document_id}-segment-{segment_number:04d}",
            document_id=document_id,
            filename=filename,
            start_page=current_start_page,
            end_page=end_page,
            chapter=current_chapter,
            section=current_section,
            subsection=current_subsection,
            text=text,
            structural_elements=list(current_structures),
            metadata={
                "file_type": document.get("file_type"),
                "page_count": document.get("page_count"),
            },
        )

        segments.append(segment)

        segment_number += 1

        current_text = []
        current_structures = []
        current_start_page = None

    for page in pages:

        page_number = page["page_number"]
        page_text = page.get("text", "").strip()

        if not page_text:
            continue

        # ---------------------------------------------------------
        # FIX:
        # Skip page 1 when it is clearly only the document
        # title/header page.
        # ---------------------------------------------------------
        if _is_title_page(page):
            continue

        structures = detect_structure(
            page_text,
            page_number
        )

        # ---------------------------------------------------------
        # Process detected structural information
        # ---------------------------------------------------------
        for structure in structures:

            if structure.element_type == "chapter":

                current_chapter = structure.text

            elif structure.element_type == "section":

                # A repeated running header (the same section title
                # printed again on a later page) is NOT a new section.
                # Without this check, a document that prints its
                # section heading on every page would be fragmented
                # into one segment per page.
                is_repeated_header = (
                    current_section is not None
                    and structure.text.strip().lower()
                    == current_section.strip().lower()
                )

                # A new section means the previous logical segment
                # should end before this page.
                if (
                    not is_repeated_header
                    and current_start_page is not None
                    and page_number != current_start_page
                ):
                    flush(page_number - 1)

                if is_repeated_header:
                    current_structures.append(structure)
                    continue

                current_section = structure.text
                current_subsection = None

            elif structure.element_type == "subsection":

                current_subsection = structure.text

            current_structures.append(structure)

        # ---------------------------------------------------------
        # Start logical segment
        # ---------------------------------------------------------
        if current_start_page is None:
            current_start_page = page_number

        # ---------------------------------------------------------
        # Preserve actual page text
        # ---------------------------------------------------------
        current_text.append(page_text)

    # -------------------------------------------------------------
    # Flush final segment
    # -------------------------------------------------------------
    if current_start_page is not None:

        last_page_number = pages[-1]["page_number"]

        flush(last_page_number)

    return segments


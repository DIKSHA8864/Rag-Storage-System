import re

from app.segmentation.models import (
    StructuralElement,
)


CHAPTER_PATTERN = re.compile(
    r"^\s*chapter\s+\d+",
    re.IGNORECASE,
)

SECTION_PATTERN = re.compile(
    r"^\s*\d+(?:\.\d+)+\.?\s+.+"
)

SUBSECTION_PATTERN = re.compile(
    r"^\s*[A-Z]\.\s+.+"
)


def detect_structure(
    text: str,
    page_number: int,
) -> list[StructuralElement]:

    detected = []

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        # --------------------------------------------------
        # Chapter
        # --------------------------------------------------

        if CHAPTER_PATTERN.match(line):

            detected.append(
                StructuralElement(
                    element_type="chapter",
                    text=line,
                    page_number=page_number,
                    level=1,
                )
            )

            continue

        # --------------------------------------------------
        # Numbered section
        #
        # Examples:
        # 1.1. Background
        # 1.2. Plaintiffs' Evaluation of Claims
        # --------------------------------------------------

        if SECTION_PATTERN.match(line):

            detected.append(
                StructuralElement(
                    element_type="section",
                    text=line,
                    page_number=page_number,
                    level=2,
                )
            )

            continue

        # --------------------------------------------------
        # Lettered subsection
        #
        # Examples:
        # A. Background
        # B. Plaintiffs' Evaluation of Claims
        # --------------------------------------------------

        if SUBSECTION_PATTERN.match(line):

            detected.append(
                StructuralElement(
                    element_type="subsection",
                    text=line,
                    page_number=page_number,
                    level=3,
                )
            )

    return detected
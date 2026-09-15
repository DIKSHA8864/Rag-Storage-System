from dataclasses import dataclass, field

from app.segmentation.document_structure import (
    detect_structure_line,
)


@dataclass
class Segment:
    """
    Represents one logically connected document segment.
    """

    segment_id: str
    document: str

    chapter: str | None = None
    section: str | None = None
    subsection: str | None = None

    start_page: int | None = None
    end_page: int | None = None

    text: str = ""

    structural_elements: list[dict] = field(
        default_factory=list
    )

    @property
    def page_count(self) -> int:

        if (
            self.start_page is None
            or self.end_page is None
        ):
            return 0

        return (
            self.end_page
            - self.start_page
            + 1
        )


def _extract_page_structures(
    page_text: str,
    page_number: int,
) -> list[dict]:
    """
    Detect structural elements and attach
    their source page number.
    """

    structures = []

    for line in page_text.splitlines():

        structure = detect_structure_line(
            line
        )

        if structure:

            structure = {
                **structure,
                "page_number": page_number,
            }

            structures.append(
                structure
            )

    return structures


def _looks_like_front_matter(
    page_number: int,
    page_text: str,
    structures: list[dict],
) -> bool:

    if page_number != 1:
        return False

    if not structures:
        return False

    words = page_text.split()

    if len(words) <= 30:
        return True

    return False


def segment_document(
    document_data: dict,
) -> list[Segment]:

    filename = document_data["filename"]

    pages = document_data.get(
        "pages",
        [],
    )

    if not pages:
        return []

    segments = []

    current_segment = None

    segment_counter = 1

    current_chapter = None
    current_section = None
    current_subsection = None

    # ==========================================================
    # PASS 1 — Establish initial context
    # ==========================================================

    first_page = pages[0]

    first_page_structures = (
        _extract_page_structures(
            first_page.get("text", ""),
            first_page["page_number"],
        )
    )

    for structure in first_page_structures:

        structure_type = structure[
            "type"
        ]

        if structure_type == "chapter":

            current_chapter = (
                structure["text"]
            )

        elif structure_type == "section":

            current_section = (
                structure["text"]
            )

        elif structure_type == "subsection":

            current_subsection = (
                structure["text"]
            )

    # ==========================================================
    # PASS 2 — Actual segmentation
    # ==========================================================

    for page in pages:

        page_number = page[
            "page_number"
        ]

        page_text = page.get(
            "text",
            "",
        ).strip()

        if not page_text:
            continue

        structures = _extract_page_structures(
            page_text,
            page_number,
        )

        front_matter = _looks_like_front_matter(
            page_number,
            page_text,
            structures,
        )

        # ------------------------------------------------------
        # Ignore title/front-matter as body content.
        # ------------------------------------------------------

        if front_matter:
            continue

        # ------------------------------------------------------
        # Create first actual segment.
        # ------------------------------------------------------

        if current_segment is None:

            current_segment = Segment(
                segment_id=(
                    f"{filename}-"
                    f"{segment_counter}"
                ),
                document=filename,
                chapter=current_chapter,
                section=current_section,
                subsection=current_subsection,
                start_page=page_number,
                end_page=page_number,
            )

            segment_counter += 1

        # ------------------------------------------------------
        # Process structures.
        # ------------------------------------------------------

        for structure in structures:

            structure_type = structure[
                "type"
            ]

            # ==================================================
            # CHAPTER
            # ==================================================

            if structure_type == "chapter":

                new_chapter = structure[
                    "text"
                ]

                same_chapter = (
                    current_chapter
                    and
                    new_chapter.lower()
                    == current_chapter.lower()
                )

                if (
                    not same_chapter
                    and current_segment.text.strip()
                ):

                    segments.append(
                        current_segment
                    )

                    current_segment = Segment(
                        segment_id=(
                            f"{filename}-"
                            f"{segment_counter}"
                        ),
                        document=filename,
                        chapter=new_chapter,
                        section=None,
                        subsection=None,
                        start_page=page_number,
                        end_page=page_number,
                    )

                    segment_counter += 1

                current_chapter = (
                    new_chapter
                )

                current_segment.chapter = (
                    current_chapter
                )

                current_segment.structural_elements.append(
                    structure
                )

            # ==================================================
            # NUMBERED SECTION
            # ==================================================

            elif structure_type == "section":

                new_section = structure[
                    "text"
                ]

                same_section = (
                    current_section
                    and
                    new_section.lower()
                    == current_section.lower()
                )

                # Repeated running header.
                if same_section:

                    current_segment.section = (
                        current_section
                    )

                    current_segment.structural_elements.append(
                        structure
                    )

                    continue

                # New genuine section.
                if (
                    current_section
                    and not same_section
                    and current_segment.text.strip()
                ):

                    segments.append(
                        current_segment
                    )

                    current_segment = Segment(
                        segment_id=(
                            f"{filename}-"
                            f"{segment_counter}"
                        ),
                        document=filename,
                        chapter=current_chapter,
                        section=new_section,
                        subsection=None,
                        start_page=page_number,
                        end_page=page_number,
                    )

                    segment_counter += 1

                current_section = (
                    new_section
                )

                current_subsection = None

                current_segment.section = (
                    current_section
                )

                current_segment.subsection = (
                    None
                )

                current_segment.structural_elements.append(
                    structure
                )

            # ==================================================
            # SUBSECTION
            # ==================================================

            elif structure_type == "subsection":

                current_subsection = (
                    structure["text"]
                )

                current_segment.subsection = (
                    current_subsection
                )

                current_segment.structural_elements.append(
                    structure
                )

        # ------------------------------------------------------
        # Add page text.
        # ------------------------------------------------------

        if current_segment.text:

            current_segment.text += "\n\n"

        current_segment.text += page_text

        current_segment.end_page = (
            page_number
        )

    # ==========================================================
    # FINAL SEGMENT
    # ==========================================================

    if (
        current_segment
        and current_segment.text.strip()
    ):

        segments.append(
            current_segment
        )

    return segments
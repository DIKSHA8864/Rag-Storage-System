from dataclasses import dataclass

from app.segmentation.semantic_segmenter import Segment


@dataclass
class SafeSplit:
    """
    Represents a safe logical split point.
    """

    page_number: int

    reason: str

    priority: int


def find_safe_split_points(
    segment: Segment,
) -> list[SafeSplit]:

    candidates = []

    for structure in segment.structural_elements:

        structure_type = structure.get(
            "type"
        )

        page_number = structure.get(
            "page_number"
        )

        if page_number is None:
            continue

        # Never split at the very beginning
        # or after the final page.
        if (
            page_number <= segment.start_page
            or page_number > segment.end_page
        ):
            continue

        if structure_type == "chapter":

            candidates.append(
                SafeSplit(
                    page_number=page_number,
                    reason="chapter_boundary",
                    priority=3,
                )
            )

        elif structure_type == "section":

            candidates.append(
                SafeSplit(
                    page_number=page_number,
                    reason="section_boundary",
                    priority=3,
                )
            )

        elif structure_type == "subsection":

            candidates.append(
                SafeSplit(
                    page_number=page_number,
                    reason="subsection_boundary",
                    priority=2,
                )
            )

    # Remove duplicate page numbers.
    unique = {}

    for candidate in candidates:

        key = candidate.page_number

        if (
            key not in unique
            or candidate.priority
            > unique[key].priority
        ):

            unique[key] = candidate

    return sorted(
        unique.values(),
        key=lambda item: item.page_number,
    )
from dataclasses import dataclass, field
from typing import Optional

from app.segmentation.semantic_segmenter import Segment


@dataclass
class TopicGroup:
    """
    Represents a logical topic containing one or more
    document segments.

    Original documents remain separate.
    """

    topic_id: str

    chapter: Optional[str]

    sections: list[str] = field(
        default_factory=list
    )

    segments: list[Segment] = field(
        default_factory=list
    )

    source_documents: list[str] = field(
        default_factory=list
    )

    total_pages: int = 0


def normalize_text(value: Optional[str]) -> str:
    """
    Normalize structural text for comparison.
    """

    if not value:
        return ""

    return " ".join(
        value.lower().split()
    )


def build_topic_key(segment: Segment) -> str:
    """
    Build a deterministic topic key.

    Currently the primary grouping signal is the chapter.
    """

    chapter = normalize_text(
        segment.chapter
    )

    if chapter:
        return chapter

    return "unknown_topic"


def group_segments_by_topic(
    segments: list[Segment],
) -> list[TopicGroup]:
    """
    Group segments belonging to the same logical topic.

    Important:
    This does NOT merge the source documents.
    It only creates a logical relationship between them.
    """

    groups: dict[str, TopicGroup] = {}

    for segment in segments:

        key = build_topic_key(segment)

        if key not in groups:

            topic_id = (
                f"topic-{len(groups) + 1:04d}"
            )

            groups[key] = TopicGroup(
                topic_id=topic_id,
                chapter=segment.chapter,
            )

        group = groups[key]

        group.segments.append(
            segment
        )

        if segment.section:

            if (
                segment.section
                not in group.sections
            ):
                group.sections.append(
                    segment.section
                )

        if (
            segment.document
            not in group.source_documents
        ):

            group.source_documents.append(
                segment.document
            )

        group.total_pages += (
            segment.page_count
        )

    return list(groups.values())
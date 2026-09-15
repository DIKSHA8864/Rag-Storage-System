from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StructuralElement:
    element_type: str
    text: str
    page_number: int
    level: int


@dataclass
class LogicalSegment:
    segment_id: str
    document_id: str
    filename: str

    start_page: int
    end_page: int

    chapter: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None

    text: str = ""

    structural_elements: list[
        StructuralElement
    ] = field(default_factory=list)

    metadata: dict = field(
        default_factory=dict
    )

    @property
    def page_count(self) -> int:
        return (
            self.end_page
            - self.start_page
            + 1
        )


@dataclass
class Chunk:
    """
    A single embedding-ready piece of text produced from a
    LogicalSegment.

    A segment can span many pages (a whole section can be dozens
    of pages long since there is no page limit), so it is split
    into smaller chunks here. Splitting always happens on sentence
    boundaries so a chunk never ends mid-sentence.
    """

    chunk_id: str
    segment_id: str
    document_id: str
    filename: str

    chunk_index: int

    start_page: int
    end_page: int

    chapter: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None

    text: str = ""

    word_count: int = 0
    approx_token_count: int = 0

    split_reason: str = "whole_segment"

    metadata: dict = field(
        default_factory=dict
    )

    @property
    def page_count(self) -> int:
        return (
            self.end_page
            - self.start_page
            + 1
        )
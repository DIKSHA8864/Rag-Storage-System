"""
Internal data structures for End User document comparison
(app/analysis/). Kept as plain dataclasses (not Pydantic) - these
never cross the API boundary directly; app/api/schemas.py defines the
Pydantic response models app/api/end_user_api.py builds from them,
mirroring how the rest of this app keeps internal dicts/dataclasses
(Chunk, LogicalSegment, ...) separate from the API's own schemas.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceEvidence:
    """One piece of cited evidence backing a comparison item's classification/narrative."""

    filename: str
    category: str
    document_id: str
    chunk_id: str
    chunk_text: str
    chapter: Optional[str]
    section: Optional[str]
    start_page: Optional[int]
    end_page: Optional[int]
    score: float


@dataclass
class ComparisonItem:
    """
    The result of comparing one chunk of the End User's submission
    against the knowledge base.

    `classification` is one of "match", "partial_match", "gap" -
    always assigned deterministically from `top_score` via
    MATCH_SCORE_THRESHOLD_MATCH/PARTIAL (config/settings.py), never by
    an LLM. `narrative` (a human-readable description of the
    relationship) is filled in afterwards by whichever
    NarrativeGenerator is configured - template or Claude - and is
    empty for "gap" items with no evidence at all (see
    app/analysis/report_builder.py's hallucination guard).
    """

    input_chunk_index: int
    input_text: str
    classification: str
    top_score: float
    sources: list[SourceEvidence] = field(default_factory=list)
    narrative: str = ""
    # A cheap, deterministic proxy for "these are about the same thing
    # but disagree on a specific detail" - see
    # app/analysis/matcher.py:_is_conflict_candidate(). Not a semantic
    # contradiction check (that needs an LLM - see
    # app/analysis/claude_narrative.py); just a numeric/date mismatch
    # signal on an otherwise-matched pair, so the "conflicts" bucket
    # isn't empty by construction when no LLM is configured.
    is_conflict: bool = False


@dataclass
class ComparisonResult:
    """
    Every input chunk's comparison result, plus the aggregate scoring
    that feeds the report's overall_match_score - see
    app/analysis/matcher.py:compare_input_to_knowledge_base().
    """

    items: list[ComparisonItem]
    coverage_ratio: float
    avg_confidence: float
    overall_match_score: float

    @property
    def has_any_evidence(self) -> bool:
        """
        False when every single input chunk came back classified
        "gap" - i.e. nothing anywhere in the submission cleared even
        MATCH_SCORE_THRESHOLD_PARTIAL. Retrieval can still technically
        return low-score rows for a "gap" item (cosine similarity
        rarely returns literally nothing), so this checks
        classification, not "did any row come back" - the hallucination-
        control trigger in app/analysis/report_builder.py: with
        nothing meeting even a partial-match bar, the report says so
        plainly instead of generating any prose.
        """

        return any(item.classification != "gap" for item in self.items)

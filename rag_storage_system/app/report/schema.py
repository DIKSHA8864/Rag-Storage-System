"""
Structured report schema for Phase 3 Client intake.

The report is assembled by app/report/builder.py and rendered through
app/report/sections.py into DOCX/PDF/image formats.

AshiLegal rules enforced here:
- StructuredReport has no client-facing aggregate score/rating.
- ReportCitation.score is retrieval relevance metadata only.
- Mock/placeholder extraction is explicitly marked for attorney review.
- Attorney review notice and disclaimer are always present.
"""

from pydantic import BaseModel, Field


class TimelineEntry(BaseModel):
    event_type: str
    description: str
    occurred_at: str


class ExtractedInputSummary(BaseModel):
    original_filename: str
    media_type: str
    content_type: str
    text: str
    provider: str
    requires_review: bool = Field(
        ...,
        description=(
            "True whenever the provider produced a mock/placeholder "
            "result rather than real extraction."
        ),
    )


class ReportCitation(BaseModel):
    """
    A citation returned directly from the Owner's knowledge-base retrieval.

    `score` is retrieval relevance metadata for internal/attorney review.
    It is NOT a case-strength score, confidence score, or client-facing rating.
    """

    filename: str
    category: str
    section: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    score: float


class StructuredReport(BaseModel):
    """
    Structured Phase 3 report consumed by all report renderers.

    No aggregate case-strength/confidence/rating field is intentionally
    present on this model.
    """

    intake_session_id: int
    matter_name: str
    generated_at: str

    summary: str
    timeline: list[TimelineEntry]
    extracted_inputs: list[ExtractedInputSummary]

    supporting_facts: list[str] = Field(default_factory=list)
    potential_causes_of_action: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)

    citations: list[ReportCitation] = Field(default_factory=list)

    attorney_review_notice: str = (
        "This report summarizes information submitted by the Client and any "
        "automated extraction performed on it. It has not been reviewed by an "
        "attorney and must not be relied upon, shared, or acted upon until an "
        "attorney has reviewed it in full, including any item marked "
        "'requires review'."
    )

    disclaimer_text: str
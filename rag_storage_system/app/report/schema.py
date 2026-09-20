"""
Structured report schema for Phase 3 Client intake (app/report/builder.py
assembles one of these; app/report/{docx,pdf,image}_renderer.py each
render the SAME instance - see sections.py for why they never diverge).

Enforces the existing AshiLegal report rules at the data-model level,
not just by convention:
  - no numeric score field exists anywhere on this model (Phase 2's
    AnalysisReport.overall_match_score has no equivalent here - intake
    summarizes what was submitted, it doesn't score it)
  - every extracted-input entry that came from a mock/placeholder
    provider carries requires_review=True, and app/report/sections.py
    always surfaces that flag in the rendered document
  - disclaimer_text and attorney_review_notice are always present -
    see app/report/builder.py for where they come from
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
        ..., description="True whenever `provider` produced a mock/placeholder result, not a real extraction."
    )


class StructuredReport(BaseModel):
    """Body app/report/builder.py produces and every ReportRenderer consumes - see this module's docstring."""

    intake_session_id: int
    matter_name: str
    generated_at: str
    summary: str
    timeline: list[TimelineEntry]
    extracted_inputs: list[ExtractedInputSummary]
    attorney_review_notice: str = (
        "This report summarizes information submitted by the Client and any "
        "automated extraction performed on it. It has not been reviewed by an "
        "attorney and must not be relied upon, shared, or acted upon until an "
        "attorney has reviewed it in full, including any item marked "
        "'requires review'."
    )
    disclaimer_text: str

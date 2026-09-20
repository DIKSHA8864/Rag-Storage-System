"""
Assembles a StructuredReport (app/report/schema.py) for one intake
session - pure data assembly, no LLM call and no per-format rendering
logic (that's app/report/{docx,pdf,image}_renderer.py, via
app/report/sections.py). Deliberately template-based rather than
LLM-generated: Phase 3's foundation must not let an LLM directly format
the final document (per AshiLegal's rules), and a template summary
built only from already-recorded facts (the session's own uploads and
timeline) has nothing to hallucinate. A future LLM-assisted summary can
slot in later as a swappable step here, the same way
app/analysis/base.py's NarrativeGenerator does for Phase 2 - it would
still only ever describe this same already-gathered data, never format
the final report.
"""

from datetime import datetime, timezone

from app.disclaimer import get_current_disclaimer_text
from app.metadata.base import MetadataRepository
from app.report.schema import ExtractedInputSummary, StructuredReport, TimelineEntry


def build_structured_report(
    intake_session_id: int, matter_name: str, metadata_repository: MetadataRepository
) -> StructuredReport:
    timeline_rows = metadata_repository.list_timeline_events(intake_session_id)
    uploaded_inputs = metadata_repository.list_uploaded_inputs(intake_session_id)

    extracted_inputs: list[ExtractedInputSummary] = []
    for uploaded_input in uploaded_inputs:
        for info in metadata_repository.list_extracted_information(uploaded_input["id"]):
            extracted_inputs.append(
                ExtractedInputSummary(
                    original_filename=uploaded_input["original_filename"],
                    media_type=uploaded_input["media_type"],
                    content_type=info["content_type"],
                    text=info["text"],
                    provider=info["provider"],
                    requires_review=bool(info["is_mock"]),
                )
            )

    summary = f"This intake session has {len(uploaded_inputs)} submitted item(s) and {len(extracted_inputs)} extracted piece(s) of content."
    if extracted_inputs:
        review_count = sum(1 for item in extracted_inputs if item.requires_review)
        summary += f" {review_count} of them require attorney review before being relied upon."
    else:
        summary += " No content has been extracted yet."

    return StructuredReport(
        intake_session_id=intake_session_id,
        matter_name=matter_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        timeline=[
            TimelineEntry(
                event_type=row["event_type"], description=row["description"], occurred_at=str(row["created_at"])
            )
            for row in timeline_rows
        ],
        extracted_inputs=extracted_inputs,
        disclaimer_text=get_current_disclaimer_text(metadata_repository),
    )

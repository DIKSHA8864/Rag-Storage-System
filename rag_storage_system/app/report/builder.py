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

RAG-backed grounding (potential causes of action, strengths/
weaknesses, missing information, library-only citations) is delegated
to app/report/rag_analysis.py - see that module's docstring for how it
retrieves against the Owner's library and degrades gracefully if
retrieval is unavailable.
"""

from datetime import datetime, timezone

from app.disclaimer import get_current_disclaimer_text
from app.intake_engine.timeline import TIMELINE_QUESTIONS
from app.metadata.base import MetadataRepository
from app.report.claude_analysis import ClaudeUnavailable, analyze_intake
from app.report.rag_analysis import _citation_dict, build_rag_sections, gather_fact_support
from app.report.schema import ExtractedInputSummary, ReportCitation, StructuredReport, TimelineEntry

# Labels for app/intake_engine categories (see engine.py's
# _category_for_state()) so Guided Intake Engine answers - mandatory
# sweep, protected activity, and the general narrative - are readable
# once folded into the same fact list as uploaded-document extractions.
_INTAKE_FACT_CATEGORY_LABELS = {
    "mandatory_sweep": "Mandatory Sweep",
    "protected_activity": "Protected Activity",
    "general": "Client Narrative",
    "follow_up": "Follow-up Answers",
    "timeline": "Key Dates",
    "documents": "Documents Available",
}
_KEY_DATE_LABELS = {q.key: q.label_en for q in TIMELINE_QUESTIONS}


def build_structured_report(
    intake_session_id: int, matter_name: str, metadata_repository: MetadataRepository
) -> StructuredReport:
    session = metadata_repository.get_intake_session_by_id(intake_session_id)
    matter_id = session["matter_id"] if session else None
    matter = metadata_repository.get_matter(matter_id) if matter_id else None
    tenant_id = matter.get("tenant_id", 1) if matter else 1

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

    intake_facts = metadata_repository.list_intake_facts(intake_session_id)

    fact_texts = [item.text for item in extracted_inputs if item.text.strip()]
    fact_texts += [
        f"[{_INTAKE_FACT_CATEGORY_LABELS.get(fact['category'], fact['category'])}] "
        f"{fact['fact_key']}: {fact['fact_value']}"
        for fact in intake_facts
        if fact["fact_value"].strip()
    ]
    fact_supports = (
        gather_fact_support(fact_texts, metadata_repository, matter_id=matter_id, tenant_id=tenant_id)
        if fact_texts else []
    )
    rag_sections = build_rag_sections(fact_supports)

    # Blueprint Phase 3: Claude writes the analysis from the intake + the
    # library passages found for it; the citation lock is enforced in code
    # (app/report/claude_analysis.py). Without a key, or if the call fails,
    # the template analysis above stands and the report says so.
    research_suggestions: list[str] = []
    try:
        if not fact_texts:
            raise ClaudeUnavailable("nothing has been recorded for this intake yet")
        analysis = analyze_intake(
            fact_texts, fact_supports, matter_name, metadata_repository, tenant_id=tenant_id,
            intake_session_id=intake_session_id, matter_id=matter_id,
        )
    except ClaudeUnavailable as exc:
        analysis_note = (
            "Analysis method: template (automated library matching; not written by Claude - "
            f"{exc})"
        )
    else:
        summary = analysis.summary
        rag_sections = {
            **rag_sections,
            "potential_causes_of_action": analysis.potential_causes_of_action,
            "strengths": analysis.strengths,
            "weaknesses": analysis.weaknesses,
            "missing_information": analysis.missing_information,
            "citations": [_citation_dict(c) for c in analysis.cited_chunks],
        }
        research_suggestions = analysis.research_suggestions
        analysis_note = (
            f"Analysis method: written by Claude ({analysis.model}) from the intake and the firm's library "
            "passages listed under Citations. Legal authority comes only from those passages."
            + (f" {len(analysis.removed_citations)} citation(s) not found in the library were removed."
               if analysis.removed_citations else "")
        )

    return StructuredReport(
        intake_session_id=intake_session_id,
        matter_name=matter_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        summary=summary,
        # The client's key dates first (as answered, at their real
        # precision - "2023-04" is never shown as a day), then the
        # session's own activity log.
        timeline=[
            TimelineEntry(
                event_type="key_date",
                description=f"{_KEY_DATE_LABELS.get(fact['fact_key'], fact['fact_key'])}: {fact['fact_value']}",
                occurred_at=fact["fact_value"].split(" (answer:")[0],
            )
            for fact in intake_facts
            if fact["category"] == "timeline"
        ] + [
            TimelineEntry(
                event_type=row["event_type"], description=row["description"], occurred_at=str(row["created_at"])
            )
            for row in timeline_rows
        ],
        extracted_inputs=extracted_inputs,
        citations=[ReportCitation(**c) for c in rag_sections["citations"]],
        potential_causes_of_action=rag_sections["potential_causes_of_action"],
        supporting_facts=rag_sections["supporting_facts"],
        strengths=rag_sections["strengths"],
        weaknesses=rag_sections["weaknesses"],
        missing_information=rag_sections["missing_information"],
        research_suggestions=research_suggestions,
        analysis_note=analysis_note,
        disclaimer_text=get_current_disclaimer_text(metadata_repository, tenant_id=tenant_id),
    )
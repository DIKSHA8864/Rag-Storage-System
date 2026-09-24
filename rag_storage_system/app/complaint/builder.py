"""
Assembles a ComplaintDraft (app/complaint/schema.py) from a Phase 3
intake fact object (app/intake_engine/, app/multimodal/'s extracted
document text) plus a set of selected cause-of-action ids from the
Owner-curated app/metadata's cause_of_action_library.

Element/fact matching is a simple keyword-overlap heuristic - not an
LLM - so a missing fact reliably becomes a bracketed placeholder rather
than a plausible-sounding invented one. This mirrors
app/report/builder.py's "template assembly, nothing to hallucinate"
approach.
"""

import re
from datetime import datetime, timezone

from app.disclaimer import get_current_disclaimer_text
from app.metadata.base import MetadataRepository
from app.complaint.schema import ComplaintCauseOfAction, ComplaintDraft, ComplaintElement, ResearchSuggestion
from app.retrieval.retriever import retrieve_for_matter

_STOPWORDS = {"the", "a", "an", "of", "to", "and", "or", "for", "was", "were", "is", "are", "that", "this"}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _find_supporting_fact(element_description: str, fact_pool: list[str]) -> str | None:
    element_keywords = _keywords(element_description)
    best_fact, best_overlap = None, 0

    for fact_text in fact_pool:
        overlap = len(element_keywords & _keywords(fact_text))
        if overlap > best_overlap:
            best_fact, best_overlap = fact_text, overlap

    return best_fact if best_overlap >= 2 else None


def build_complaint_draft(
    intake_session_id: int,
    matter_id: int,
    matter_name: str,
    cause_of_action_ids: list[int],
    metadata_repository: MetadataRepository,
    tenant_id: int = 1,
) -> ComplaintDraft:
    intake_facts = metadata_repository.list_intake_facts(intake_session_id)
    fact_pool = [f"{f['fact_key']}: {f['fact_value']}" for f in intake_facts if f["fact_value"].strip()]

    uploaded_inputs = metadata_repository.list_uploaded_inputs(intake_session_id)
    for uploaded_input in uploaded_inputs:
        for info in metadata_repository.list_extracted_information(uploaded_input["id"]):
            if info["text"].strip():
                fact_pool.append(info["text"])

    causes_of_action = []
    for cause_id in cause_of_action_ids:
        curated = metadata_repository.get_cause_of_action(cause_id, tenant_id=tenant_id)
        if curated is None:
            continue

        elements = []
        for element_description in curated["elements"]:
            supporting_fact = _find_supporting_fact(element_description, fact_pool)
            elements.append(
                ComplaintElement(
                    description=element_description,
                    satisfied_by=supporting_fact,
                    placeholder=None if supporting_fact else f"[ATTORNEY TO PROVIDE: {element_description}]",
                )
            )

        try:
            research_hits = retrieve_for_matter(curated["name"], matter_id, top_k=3, tenant_id=tenant_id)
        except Exception:
            research_hits = []

        causes_of_action.append(
            ComplaintCauseOfAction(
                cause_of_action_id=curated["id"],
                name=curated["name"],
                authority_citation=curated["authority_citation"],
                elements=elements,
                research_suggestions=[
                    ResearchSuggestion(
                        filename=hit["filename"], category=hit["category"],
                        chunk_text=hit["chunk_text"], score=hit["final_score"],
                    )
                    for hit in research_hits
                ],
            )
        )

    return ComplaintDraft(
        intake_session_id=intake_session_id,
        matter_name=matter_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        plaintiff_name=matter_name,
        causes_of_action=causes_of_action,
        disclaimer_text=get_current_disclaimer_text(metadata_repository),
    )
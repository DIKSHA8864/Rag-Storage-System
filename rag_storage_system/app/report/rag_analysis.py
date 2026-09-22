"""
RAG-backed grounding for the Client intake StructuredReport
(app/report/schema.py, builder.py). Retrieves relevant Owner-library
chunks for each fact extracted from the Client's intake
(app/multimodal/'s extracted_information) via the same hybrid
retrieval pipeline Phase 2's End User Q&A/compare features use
(app/retrieval/retriever.py) - never a separate or weaker retrieval
path - and uses ONLY those chunks to derive potential causes of
action, strengths, weaknesses, and missing information/documents.

LIBRARY-ONLY CITATIONS: every citation this module produces is built
directly from a chunk retrieve() actually returned for one of the
Client's own facts - there is no path that lets a citation be invented
or drawn from outside the retrieved set.

Classification (whether a fact is well-supported, weakly supported, or
unsupported) reuses Phase 2's app/analysis/matcher.py:classify_score()
directly - the exact same MATCH_SCORE_THRESHOLD_MATCH/PARTIAL bar
(config/settings.py) judges a fact here as judges a Phase 2 comparison
item, not a separately-tuned one.

Retrieval failure (no Postgres/pgvector reachable, or the embedding
model can't load - a real limitation in network-restricted
environments) degrades this to an honest "could not be checked" note
per fact rather than raising - a report must still generate even when
the knowledge base is temporarily unreachable, the same resilience
philosophy as app/analysis/claude_narrative.py's and
app/analysis/answer_generation.py's fallbacks.
"""

import logging
from dataclasses import dataclass, field

from app.analysis.matcher import classify_score
from app.metadata.base import MetadataRepository
from typing import Optional

from app.retrieval.retriever import retrieve, retrieve_for_matter
from app.retrieval_settings import get_current_retrieval_settings

logger = logging.getLogger(__name__)


@dataclass
class FactSupport:
    """One extracted fact's grounding result - the structured fact object that feeds the report."""

    fact_text: str
    classification: str  # "match" | "partial_match" | "gap" | "unavailable"
    citations: list[dict] = field(default_factory=list)


def _citation_dict(chunk: dict) -> dict:
    return {
        "filename": chunk["filename"],
        "category": chunk["category"],
        "section": chunk.get("section"),
        "start_page": chunk.get("start_page"),
        "end_page": chunk.get("end_page"),
        "score": chunk["final_score"],
    }


def gather_fact_support(
    facts: list[str], metadata_repository: MetadataRepository, matter_id: Optional[int] = None
) -> list[FactSupport]:
    """
    Run retrieval for each fact INDEPENDENTLY (never one blended query
    for the whole intake - that would blur which specific fact a
    citation actually supports) and classify it by its single
    best-scoring hit.

    When `matter_id` is given, retrieval also includes that Matter's
    own ingested documents (app/matter_rag/) alongside the Owner's
    library - never any other Matter's namespace (see
    app/retrieval/retriever.py's retrieve_for_matter()).
    """

    settings = get_current_retrieval_settings(metadata_repository)
    results = []

    for fact_text in facts:
        try:
            if matter_id is not None:
                chunks = retrieve_for_matter(fact_text, matter_id, top_k=settings.top_k)
            else:
                chunks = retrieve(fact_text, top_k=settings.top_k)
        except Exception:
            logger.warning(
                "Knowledge-base retrieval unavailable while grounding fact %r - "
                "recording it as unavailable rather than failing report generation.",
                fact_text, exc_info=True,
            )
            results.append(FactSupport(fact_text=fact_text, classification="unavailable"))
            continue

        classification = classify_score(chunks[0]["final_score"]) if chunks else "gap"
        citations = [_citation_dict(c) for c in chunks if classify_score(c["final_score"]) != "gap"]

        results.append(FactSupport(fact_text=fact_text, classification=classification, citations=citations))

    return results


def build_rag_sections(fact_supports: list[FactSupport]) -> dict:
    """Deterministic, trivially-grounded assembly of the RAG-backed report sections from already-classified fact support."""

    supporting_facts = [fs.fact_text for fs in fact_supports]

    strengths = [
        f"'{fs.fact_text}' is supported by knowledge-base material: "
        + ", ".join(
            c["filename"] + (f" (section {c['section']})" if c.get("section") else "") for c in fs.citations
        )
        for fs in fact_supports
        if fs.classification == "match"
    ]

    weaknesses = [
        f"'{fs.fact_text}' has only limited support in the knowledge base and may need additional documentation."
        for fs in fact_supports
        if fs.classification == "partial_match"
    ]

    missing_information = []
    for fs in fact_supports:
        if fs.classification == "gap":
            missing_information.append(
                f"No related material was found in the knowledge base for: '{fs.fact_text}'. "
                "Attorney should determine whether additional documentation is needed."
            )
        elif fs.classification == "unavailable":
            missing_information.append(
                f"Knowledge-base retrieval was unavailable when this report was generated - "
                f"'{fs.fact_text}' could not be cross-checked against the library."
            )

    potential_causes_of_action = []
    seen_categories = set()
    for fs in fact_supports:
        if fs.classification != "match":
            continue
        for citation in fs.citations:
            if citation["category"] in seen_categories:
                continue
            seen_categories.add(citation["category"])
            potential_causes_of_action.append(
                f"Knowledge-base material in '{citation['category']}' may be relevant "
                f"(see {citation['filename']}) - this is not a legal conclusion and "
                "must be evaluated by an attorney."
            )

    citations = [citation for fs in fact_supports for citation in fs.citations]

    return {
        "supporting_facts": supporting_facts,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "missing_information": missing_information,
        "potential_causes_of_action": potential_causes_of_action,
        "citations": citations,
    }
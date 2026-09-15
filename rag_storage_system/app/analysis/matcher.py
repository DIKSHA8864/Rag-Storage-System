"""
The matching/comparison logic (Phase 3 of the End User pipeline):
takes an End User's embedded chunks (app/analysis/ingestion.py) and,
for each one, finds and classifies its best support in the knowledge
base using the same hybrid retrieval pipeline built for POST /search
(app/retrieval/retriever.py) - so "compared against the knowledge
base" means exactly what it says, not a separate, parallel search
implementation.

MATCH-SCORE METHODOLOGY (config/settings.py):

Classification of one chunk is a threshold on its single best
knowledge-base match's retrieval score (cosine similarity fused with
keyword match via app/retrieval/reranker.py, already in [0, 1]):

    score >= MATCH_SCORE_THRESHOLD_MATCH     -> "match"
    score >= MATCH_SCORE_THRESHOLD_PARTIAL   -> "partial_match"
    otherwise (including no results at all)  -> "gap"

The submission's overall_match_score (0-100) is a weighted combination
of two independent signals, both computed here, neither ever decided
by an LLM:

    coverage_ratio  = (matches + 0.5 x partial_matches) / total_chunks
    avg_confidence  = mean(top_score across every chunk, 0 for gaps)

    overall_match_score = 100 x (
        MATCH_SCORE_COVERAGE_WEIGHT   x coverage_ratio +
        MATCH_SCORE_CONFIDENCE_WEIGHT x avg_confidence
    )

coverage_ratio answers "how much of what was submitted has support in
the knowledge base" (a document that's 90% covered but only weakly so
scores differently from one that's 50% covered but with strong
matches) - avg_confidence answers "how strong is that support". Both
weights and both thresholds are config (.env), not hardcoded - tune
them per how strict a match should be considered "found" without
touching this module.
"""

import re
from typing import Optional

from app.analysis.models import ComparisonItem, ComparisonResult, SourceEvidence
from app.retrieval.retriever import retrieve
from config.settings import get_settings

# Retrieve a few candidates per chunk (not just the top 1) so the
# report can cite corroborating/alternative evidence, not just the
# single closest chunk.
_SOURCES_PER_ITEM = 3

# A crude but deterministic "these might conflict" signal: two chunks
# retrieval considers a match/partial_match (i.e. clearly about the
# same subject) that nonetheless cite different numbers/dates/amounts.
# Not a semantic contradiction check - see ComparisonItem.is_conflict.
_NUMBER_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|days?|months?|years?|hours?|weeks?|dollars?|usd|\$)?\b",
    re.IGNORECASE,
)


def _extract_numbers(text: str) -> set[str]:
    return {match.strip().lower() for match in _NUMBER_PATTERN.findall(text)}


def _is_conflict_candidate(input_text: str, classification: str, top_source: Optional[SourceEvidence]) -> bool:
    if classification not in ("match", "partial_match") or top_source is None:
        return False

    input_numbers = _extract_numbers(input_text)
    source_numbers = _extract_numbers(top_source.chunk_text)

    return bool(input_numbers) and bool(source_numbers) and input_numbers.isdisjoint(source_numbers)


def classify_score(score: float) -> str:
    """Deterministic score -> classification, per this module's docstring."""

    settings = get_settings()

    if score >= settings.match_score_threshold_match:
        return "match"

    if score >= settings.match_score_threshold_partial:
        return "partial_match"

    return "gap"


def _to_source_evidence(hit: dict) -> SourceEvidence:
    return SourceEvidence(
        filename=hit["filename"],
        category=hit["category"],
        document_id=hit["document_id"],
        chunk_id=hit["chunk_id"],
        chunk_text=hit["chunk_text"],
        chapter=hit.get("chapter"),
        section=hit.get("section"),
        start_page=hit.get("start_page"),
        end_page=hit.get("end_page"),
        score=hit["final_score"],
    )


def compare_input_to_knowledge_base(
    input_chunks: list[dict],
    category: Optional[str] = None,
) -> ComparisonResult:
    """
    Compare every one of an End User's submitted chunks against the
    knowledge base and compute the submission's overall match score.

    `input_chunks` is app/analysis/ingestion.py's output (each a dict
    with at least "text"); `category` optionally restricts retrieval
    to one knowledge-base category, same as POST /search.
    """

    items: list[ComparisonItem] = []

    for index, chunk in enumerate(input_chunks):
        hits = retrieve(chunk["text"], top_k=_SOURCES_PER_ITEM, category=category)

        top_score = hits[0]["final_score"] if hits else 0.0
        classification = classify_score(top_score)
        sources = [_to_source_evidence(hit) for hit in hits]

        items.append(
            ComparisonItem(
                input_chunk_index=index,
                input_text=chunk["text"],
                classification=classification,
                top_score=top_score,
                sources=sources,
                is_conflict=_is_conflict_candidate(
                    chunk["text"], classification, sources[0] if sources else None
                ),
            )
        )

    return _score(items)


def _score(items: list[ComparisonItem]) -> ComparisonResult:
    settings = get_settings()

    total = len(items)

    if total == 0:
        return ComparisonResult(
            items=items, coverage_ratio=0.0, avg_confidence=0.0, overall_match_score=0.0
        )

    matched = sum(1 for item in items if item.classification == "match")
    partial = sum(1 for item in items if item.classification == "partial_match")

    coverage_ratio = (matched + 0.5 * partial) / total
    avg_confidence = sum(item.top_score for item in items) / total

    overall_match_score = round(
        100
        * (
            settings.match_score_coverage_weight * coverage_ratio
            + settings.match_score_confidence_weight * avg_confidence
        ),
        1,
    )

    return ComparisonResult(
        items=items,
        coverage_ratio=coverage_ratio,
        avg_confidence=avg_confidence,
        overall_match_score=overall_match_score,
    )

"""
Assembles the final structured analysis report (Phase 5 of the End
User pipeline) from a ComparisonResult (app/analysis/matcher.py) and
whichever NarrativeGenerator is configured (app/analysis/__init__.py).

HALLUCINATION CONTROL (Phase 6):
  - Whole-report guard: if not one input chunk cleared even the
    partial-match threshold (ComparisonResult.has_any_evidence is
    False), the narrative generator is never called at all -
    executive_summary is hardcoded to the fixed
    "Insufficient information found in the available knowledge base."
    and overall_match_score is 0. An LLM is never given the chance to
    invent an answer when there is nothing to answer from.
  - Per-item guard: every "gap" item's narrative is always the fixed
    "No matching information found..." string, set here directly -
    never something a NarrativeGenerator wrote, even when Claude is
    configured.
  - Provenance: every report item is tagged "retrieved" (the sources
    themselves - raw facts from the knowledge base), "generated" (the
    narrative prose - interpretation, by template or LLM, of those
    facts), or "recommendation" (actionable inference) - see
    PROVENANCE_LEGEND below, also returned in every report so a caller
    never has to guess which is which.
  - A NarrativeGenerator failure (bad JSON, API error - see
    ClaudeNarrativeGenerator) falls back to TemplateNarrativeGenerator
    rather than surfacing a broken report.
"""

from dataclasses import asdict
from typing import Optional

from app.analysis import get_narrative_generator
from app.analysis.base import ReportNarrative
from app.analysis.matcher import compare_input_to_knowledge_base
from app.analysis.models import ComparisonItem, ComparisonResult
from config.settings import get_settings

INSUFFICIENT_EVIDENCE_MESSAGE = "Insufficient information found in the available knowledge base."
NO_ITEM_EVIDENCE_MESSAGE = "No matching information found in the knowledge base for this item."

PROVENANCE_LEGEND = {
    "retrieved": "Directly from the knowledge base - chunk text, classification, and match score.",
    "generated": "Interpretation of the retrieved evidence, written by the narrative provider.",
    "recommendation": "Actionable suggestion inferred from gaps/partial matches, not a retrieved fact.",
}


def _item_to_dict(item: ComparisonItem) -> dict:
    return {
        "input_chunk_index": item.input_chunk_index,
        "input_text": item.input_text,
        "classification": item.classification,
        "top_score": round(item.top_score, 3),
        "is_conflict": item.is_conflict,
        "narrative": {"text": item.narrative, "provenance": "generated"},
        "sources": [{**asdict(source), "provenance": "retrieved"} for source in item.sources],
    }


def _empty_report(comparison: ComparisonResult) -> dict:
    settings = get_settings()

    gaps = [_item_to_dict(item) for item in comparison.items]

    return {
        "executive_summary": {"text": INSUFFICIENT_EVIDENCE_MESSAGE, "provenance": "generated"},
        "overall_match_score": 0.0,
        "match_score_breakdown": {
            "coverage_ratio": 0.0,
            "avg_confidence": round(comparison.avg_confidence, 3),
            "coverage_weight": settings.match_score_coverage_weight,
            "confidence_weight": settings.match_score_confidence_weight,
        },
        "detailed_matching": {
            "similarities": [],
            "differences": [],
            "gaps": gaps,
            "conflicts": [],
        },
        "recommendations": [],
        "sources": [],
        "insufficient_evidence": True,
        "provenance_legend": PROVENANCE_LEGEND,
    }


def _generate_narrative(comparison: ComparisonResult) -> ReportNarrative:
    generator = get_narrative_generator()

    try:
        return generator.generate(comparison)
    except Exception:
        # A hosted-LLM provider can fail (bad JSON, API/network error) -
        # degrade to the deterministic template rather than break the
        # report. See ClaudeNarrativeGenerator's docstring.
        from app.analysis.template_narrative import TemplateNarrativeGenerator

        return TemplateNarrativeGenerator().generate(comparison)


def build_analysis_report(input_chunks: list[dict], category: Optional[str] = None) -> dict:
    """
    Run the full comparison + narrative + hallucination-guard pipeline
    for an End User's already-embedded submission (see
    app/analysis/ingestion.py) and return the structured report dict
    app/api/end_user_api.py serializes as the AnalysisReport response.
    """

    comparison = compare_input_to_knowledge_base(input_chunks, category=category)

    if not comparison.has_any_evidence:
        return _empty_report(comparison)

    narrative = _generate_narrative(comparison)

    for item in comparison.items:
        item.narrative = (
            NO_ITEM_EVIDENCE_MESSAGE
            if item.classification == "gap"
            else narrative.item_narratives.get(item.input_chunk_index, "")
        )

    similarities = [
        _item_to_dict(item) for item in comparison.items if item.classification == "match"
    ]
    differences = [
        _item_to_dict(item) for item in comparison.items if item.classification == "partial_match"
    ]
    gaps = [_item_to_dict(item) for item in comparison.items if item.classification == "gap"]
    conflicts = [_item_to_dict(item) for item in comparison.items if item.is_conflict]

    seen_chunk_ids: set[str] = set()
    all_sources = []
    for item in comparison.items:
        for source in item.sources:
            if source.chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(source.chunk_id)
                all_sources.append({**asdict(source), "provenance": "retrieved"})

    settings = get_settings()

    return {
        "executive_summary": {"text": narrative.executive_summary, "provenance": "generated"},
        "overall_match_score": comparison.overall_match_score,
        "match_score_breakdown": {
            "coverage_ratio": round(comparison.coverage_ratio, 3),
            "avg_confidence": round(comparison.avg_confidence, 3),
            "coverage_weight": settings.match_score_coverage_weight,
            "confidence_weight": settings.match_score_confidence_weight,
        },
        "detailed_matching": {
            "similarities": similarities,
            "differences": differences,
            "gaps": gaps,
            "conflicts": conflicts,
        },
        "recommendations": [
            {"text": text, "provenance": "recommendation"} for text in narrative.recommendations
        ],
        "sources": all_sources,
        "insufficient_evidence": False,
        "provenance_legend": PROVENANCE_LEGEND,
    }

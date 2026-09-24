"""
Default NarrativeGenerator - fully deterministic, rule-based text.
Free, needs no API key, and always available, which is why
get_narrative_generator() (app/analysis/__init__.py) falls back to
this whenever NARRATIVE_PROVIDER isn't "claude" or ANTHROPIC_API_KEY
isn't set. Every sentence it writes is built directly from already-
computed classifications/scores/sources (app/analysis/matcher.py) - it
never infers or elaborates beyond that data, so there is nothing here
for a hallucination guard to catch.
"""

from app.analysis.base import NarrativeGenerator, ReportNarrative
from app.analysis.models import ComparisonItem, ComparisonResult

_EXCERPT_LENGTH = 160


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _EXCERPT_LENGTH else text[: _EXCERPT_LENGTH - 1].rstrip() + "…"


def _cite(item: ComparisonItem) -> str:
    source = item.sources[0]
    location = source.section or (
        f"pp. {source.start_page}-{source.end_page}" if source.start_page else None
    )
    location_part = f", {location}" if location else ""
    return f"'{source.filename}'{location_part}"


def _item_narrative(item: ComparisonItem) -> str:
    citation = _cite(item)
    confidence_pct = round(item.top_score * 100)

    if item.classification == "match":
        return f"Closely matches {citation} (confidence {confidence_pct}%)."

    if item.classification == "partial_match":
        return (
            f"Partially matches {citation} (confidence {confidence_pct}%) - "
            "wording or scope differs; review both versions side by side."
        )

    return (
        f"Weak match only (closest reference {citation}, confidence "
        f"{confidence_pct}%, below the match threshold)."
    )


class TemplateNarrativeGenerator(NarrativeGenerator):

    def generate(self, comparison: ComparisonResult, tenant_id: int = 1) -> ReportNarrative:
        total = len(comparison.items)
        matched = sum(1 for item in comparison.items if item.classification == "match")
        partial = sum(1 for item in comparison.items if item.classification == "partial_match")
        gaps = sum(1 for item in comparison.items if item.classification == "gap")

        executive_summary = (
            f"The submission was compared against the knowledge base across {total} "
            f"section{'s' if total != 1 else ''}: {matched} fully supported, {partial} "
            f"partially supported, and {gaps} with no adequate support found. Overall "
            f"match score: {comparison.overall_match_score}/100 (coverage "
            f"{round(comparison.coverage_ratio * 100)}%, average match confidence "
            f"{round(comparison.avg_confidence * 100)}%)."
        )

        item_narratives = {
            item.input_chunk_index: _item_narrative(item)
            for item in comparison.items
            if item.sources
        }

        recommendations = []

        for item in comparison.items:
            excerpt = _excerpt(item.input_text)

            if item.classification == "gap":
                recommendations.append(
                    f'No knowledge-base support was found for: "{excerpt}" - confirm '
                    "this requirement is intentional, or add supporting documentation "
                    "to the knowledge base."
                )
            elif item.classification == "partial_match":
                recommendations.append(
                    f'Review for consistency against {_cite(item)}: "{excerpt}"'
                )

        return ReportNarrative(
            executive_summary=executive_summary,
            item_narratives=item_narratives,
            recommendations=recommendations,
        )

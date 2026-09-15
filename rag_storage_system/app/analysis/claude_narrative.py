"""
Claude-backed NarrativeGenerator. Opt-in - set NARRATIVE_PROVIDER=claude
and ANTHROPIC_API_KEY (config/settings.py / .env); get_narrative_generator()
falls back to TemplateNarrativeGenerator otherwise.

HALLUCINATION CONTROL: Claude is given only the already-computed
comparison data (classifications, scores, source excerpts - never the
full knowledge base, never anything it could look up on its own) and
is instructed to write about nothing else. It never decides
classifications or the match score itself - those come from
app/analysis/matcher.py and are fixed before this is ever called. One
request covers the whole report (executive summary + every item's
narrative + recommendations) so they read as one coherent document
and so a multi-chunk submission costs one call, not N.

A malformed response (bad JSON, API error) raises rather than
returning something silently wrong - app/analysis/report_builder.py
catches that and falls back to TemplateNarrativeGenerator, so a Claude
hiccup degrades the report instead of breaking it.
"""

import json

import anthropic

from app.analysis.base import NarrativeGenerator, ReportNarrative
from app.analysis.models import ComparisonResult
from config.settings import get_settings

_SYSTEM_PROMPT = """\
You write sections of a document-comparison report for an End User \
who submitted a document/query to be checked against an \
organization's knowledge base.

You are given, for each part of the submission: its classification \
(already decided - match / partial_match / gap), its match score \
(already computed), and up to 3 knowledge-base source excerpts \
(filename, section/page, text) that retrieval found for it.

STRICT RULES:
- Only state facts present in the input excerpt or the source \
excerpts you are given below. Never introduce outside knowledge, \
assumptions, or invented details - you have no access to the \
knowledge base beyond what is shown to you here.
- Never change or second-guess a classification or score - describe \
the ones given to you.
- Do not write a narrative for any item not listed under "items" \
below (items with no sources are omitted on purpose - never invent \
one for them).
- Every recommendation must reference a specific input excerpt (and \
the source filename, if one was given for that item).
- Neutral, precise, evidence-based tone - this is a compliance/\
analysis report, not marketing copy.
- Respond with ONLY a single JSON object matching the schema in the \
user message. No markdown code fences, no commentary outside the JSON.
"""


def _build_user_message(comparison: ComparisonResult) -> str:
    items_payload = [
        {
            "index": item.input_chunk_index,
            "classification": item.classification,
            "top_score": round(item.top_score, 3),
            "input_excerpt": item.input_text[:500],
            "sources": [
                {
                    "filename": source.filename,
                    "section": source.section,
                    "chapter": source.chapter,
                    "pages": [source.start_page, source.end_page],
                    "score": round(source.score, 3),
                }
                for source in item.sources
            ],
        }
        for item in comparison.items
        if item.sources
    ]

    payload = {
        "overall_match_score": comparison.overall_match_score,
        "coverage_ratio": round(comparison.coverage_ratio, 3),
        "avg_confidence": round(comparison.avg_confidence, 3),
        "items": items_payload,
    }

    schema = (
        "Return a JSON object with exactly these keys:\n"
        '  "executive_summary": string (2-4 sentences)\n'
        '  "item_narratives": object mapping each item\'s "index" (as a JSON string key) to a '
        "1-2 sentence description of how well that item is supported, citing the source "
        "filename/section - one entry per item listed below, no more, no fewer\n"
        '  "recommendations": array of short actionable strings, one per "partial_match" or '
        '"gap" item, each referencing that item\'s input_excerpt and, if present, its source filename\n'
    )

    return f"{schema}\nDATA:\n{json.dumps(payload, ensure_ascii=False)}"


class ClaudeNarrativeGenerator(NarrativeGenerator):

    def __init__(self):
        settings = get_settings()

        if not settings.anthropic_api_key:
            raise RuntimeError(
                "NARRATIVE_PROVIDER=claude requires ANTHROPIC_API_KEY to be set."
            )

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.analysis_model

    def generate(self, comparison: ComparisonResult) -> ReportNarrative:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_message(comparison)}],
        )

        text = "".join(block.text for block in response.content if block.type == "text")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Claude narrative response was not valid JSON: {exc}") from exc

        try:
            return ReportNarrative(
                executive_summary=data["executive_summary"],
                item_narratives={int(k): v for k, v in data["item_narratives"].items()},
                recommendations=list(data["recommendations"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Claude narrative response had an unexpected shape: {exc}") from exc

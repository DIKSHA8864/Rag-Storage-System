"""
Owner analytics (Blueprint Phase 5): how the system is being used and how
well it is answering, for the caller's organization only, over the last
N days. Everything is computed from records the system already keeps -
the per-call usage log (llm_usage_log), intake sessions/interviews/
reports, and uploads. Nothing is estimated except cost, and cost is only
shown for models the owner has priced (LLM_PRICES) - otherwise it is
left empty rather than guessed.

    GET /admin/analytics?days=30
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.api.schemas import AnalyticsResponse
from app.security.auth import require_owner_role
from config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["analytics"], dependencies=[Depends(require_owner_role)])

# Answer outcomes the usage log records (app/analysis/answer_generation.py).
HONEST_GAP = "insufficient_evidence"
GROUNDED = "grounded"
_TOP_SOURCES = 10


def _prices() -> dict[str, tuple[float, float]]:
    """LLM_PRICES='{"<model>": [<input>, <output>]}' - USD per million input / output tokens, per model."""

    raw = get_settings().llm_prices.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return {model: (float(pair[0]), float(pair[1])) for model, pair in parsed.items()}
    except (ValueError, TypeError, IndexError, AttributeError):
        logger.warning("LLM_PRICES is not valid JSON of {model: [input, output]} - cost is not shown.")
        return {}


def _day(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    return str(value)[:10]


def _percentile(values: list[int], share: float):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(days: int = Query(30, ge=1, le=365), owner: dict = Depends(require_owner_role)) -> AnalyticsResponse:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    tenant_id = owner["tenant_id"]
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    since = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat()

    rows = repo.list_llm_usage_since(tenant_id, since)
    questions = [r for r in rows if r["is_question"]]

    per_day = Counter(_day(r["created_at"]) for r in questions)
    daily = [
        {"date": (start + timedelta(days=offset)).isoformat(), "count": per_day.get((start + timedelta(days=offset)).isoformat(), 0)}
        for offset in range(days)
    ]
    outcomes = Counter(r["citation_check_result"] or "unknown" for r in questions)
    latencies = [int(r["latency_ms"]) for r in questions if r["latency_ms"]]

    prices = _prices()
    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    for row in rows:
        entry = by_model[row["model"]]
        entry["calls"] += 1
        entry["input_tokens"] += int(row["input_tokens"] or 0)
        entry["output_tokens"] += int(row["output_tokens"] or 0)
    models = []
    total_cost = 0.0
    all_priced = True
    for model, entry in sorted(by_model.items(), key=lambda item: -item[1]["calls"]):
        cost = None
        if model in prices:
            cost = round(entry["input_tokens"] / 1e6 * prices[model][0] + entry["output_tokens"] / 1e6 * prices[model][1], 4)
            total_cost += cost
        elif entry["input_tokens"] or entry["output_tokens"]:
            all_priced = False
        models.append({"model": model, **entry, "estimated_cost_usd": cost})

    # Most-cited library sources: the chunks behind grounded answers, named by the current index.
    chunk_counts = Counter(chunk for r in questions if r["citation_check_result"] == GROUNDED for chunk in r["retrieved_chunk_ids"])
    top_sources: list[dict] = []
    if chunk_counts:
        try:
            names = storage_api.get_vector_store().chunk_sources(list(chunk_counts), tenant_id)
        except Exception:
            logger.warning("Top sources unavailable: the search index could not be read.", exc_info=True)
            names = {}
        by_file: Counter = Counter()
        for chunk_id, count in chunk_counts.items():
            source = names.get(chunk_id)
            if source and not source["category"].startswith("matter-"):
                by_file[(source["category"], source["filename"])] += count
        top_sources = [
            {"category": category, "filename": filename, "count": count}
            for (category, filename), count in by_file.most_common(_TOP_SOURCES)
        ]

    library = Counter(d.get("status", "Uploaded") for d in repo.list_documents(tenant_id=tenant_id))

    return AnalyticsResponse(
        days=days,
        since=start.isoformat(),
        questions={
            "total": len(questions),
            "per_day": daily,
            "by_purpose": dict(Counter(r["purpose"] for r in questions)),
            "outcomes": dict(outcomes),
            # Share of all questions where the library had no authority on the point.
            "honest_gap_rate": round(outcomes.get(HONEST_GAP, 0) / len(questions), 4) if questions else None,
            "median_latency_ms": _percentile(latencies, 0.5),
            "p95_latency_ms": _percentile(latencies, 0.95),
        },
        usage={
            "calls": len(rows),
            "input_tokens": sum(m["input_tokens"] for m in models),
            "output_tokens": sum(m["output_tokens"] for m in models),
            "estimated_cost_usd": round(total_cost, 4) if prices and all_priced else None,
            "by_model": models,
        },
        intake=repo.intake_funnel_counts(tenant_id, since),
        library_by_status=dict(library),
        top_sources=top_sources,
    )

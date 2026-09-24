"""
Records every Claude API call's token usage/latency, so per-Matter
and per-session LLM cost is queryable (Milestone 7's "cost
instrumentation per session"). Call this immediately after any
anthropic.Anthropic()/AsyncAnthropic() .messages.create() call - see
app/analysis/claude_narrative.py and app/analysis/answer_generation.py.
"""

import time
from contextlib import contextmanager
from typing import Optional


def log_rag_query(
    purpose: str, query: str, results: list[dict], model: str,
    input_tokens: int, output_tokens: int, latency_ms: int, citation_check_result: str,
    matter_id: Optional[int] = None, intake_session_id: Optional[int] = None, tenant_id: int = 1,
) -> None:
    """
    Records one grounded-answer request - Owner research, Matter
    research, or End User Q&A (app/analysis/answer_generation.py's
    stream_grounded_answer(), the one shared implementation all three
    call) - to the SAME llm_usage_log table track_llm_call() below
    writes to. Not a second logging system: just this table's other,
    per-query shape (query text, the retrieved chunk ids/scores, and
    the citation-check outcome) alongside the model/token/latency
    columns track_llm_call() already fills in for narrative generation.
    Best-effort like track_llm_call() - observability must never break
    the actual RAG answer it's describing.
    """

    from app.api import storage_api

    try:
        storage_api.metadata_repository.add_llm_usage_log(
            matter_id=matter_id, intake_session_id=intake_session_id, purpose=purpose,
            model=model, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms,
            query_text=query,
            retrieved_chunk_ids=[r.get("chunk_id") for r in results],
            retrieved_chunk_scores=[r.get("final_score") for r in results],
            citation_check_result=citation_check_result,
            tenant_id=tenant_id,
        )
    except Exception:
        pass  # best-effort - never breaks the actual RAG answer it's describing


@contextmanager
def track_llm_call(
    purpose: str, model: str, matter_id: Optional[int] = None, intake_session_id: Optional[int] = None,
    tenant_id: int = 1,
):
    """
    Usage:
        with track_llm_call("narrative_generation", model, matter_id=..., intake_session_id=...) as tracker:
            response = client.messages.create(...)
            tracker(response.usage.input_tokens, response.usage.output_tokens)
    """

    from app.api import storage_api

    start = time.perf_counter()
    usage = {"input_tokens": 0, "output_tokens": 0}

    def _record(input_tokens: int, output_tokens: int) -> None:
        usage["input_tokens"] = input_tokens
        usage["output_tokens"] = output_tokens

    try:
        yield _record
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        try:
            storage_api.metadata_repository.add_llm_usage_log(
                matter_id=matter_id, intake_session_id=intake_session_id, purpose=purpose,
                model=model, input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                latency_ms=latency_ms, tenant_id=tenant_id,
            )
        except Exception:
            pass  # usage logging is best-effort - never breaks the actual LLM call it's wrapping
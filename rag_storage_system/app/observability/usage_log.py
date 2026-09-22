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


@contextmanager
def track_llm_call(purpose: str, model: str, matter_id: Optional[int] = None, intake_session_id: Optional[int] = None):
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
                latency_ms=latency_ms,
            )
        except Exception:
            pass  # usage logging is best-effort - never breaks the actual LLM call it's wrapping
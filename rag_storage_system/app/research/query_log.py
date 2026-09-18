"""
Per-request observability for POST /ask.

Work Plan Milestone 2: "log every request - query, retrieved chunk IDs
+ scores, model, token usage, latency, citation-check result - to
Postgres for the owner's audit and tuning."

Separate from app/security/audit_log.py, which records file operations
to a JSONL file. This is queryable: "show me every answer where a
citation was stripped last week" is a SQL query, and that question is
the whole point of a citation lock you can prove.

Logging is best-effort - a failure here never fails the owner's
answer.
"""

import json

from psycopg import connect

from config.settings import get_settings


def get_connection():
    settings = get_settings()
    return connect(settings.postgres_dsn)


def log_ask(result, *, query: str, owner_id=None, thread_id=None,
            category=None) -> None:
    """Record one /ask request. `result` is an AnswerResult."""

    retrieved = [
        {
            "chunk_id": source["chunk_id"],
            "filename": source["filename"],
            "section": source.get("section"),
            "score": source["score"],
        }
        for source in result.sources
    ]

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ask_query_logs
                        (owner_id, thread_id, query, category, retrieved,
                         top_score, answered, model, prompt_version,
                         input_tokens, output_tokens, latency_ms,
                         citation_status, citation_detail)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        owner_id, thread_id, query, category,
                        json.dumps(retrieved), result.top_score,
                        result.answered_by_model, result.model,
                        result.prompt_version, result.input_tokens,
                        result.output_tokens, result.latency_ms,
                        result.status, json.dumps(result.citation_detail),
                    ),
                )
            conn.commit()
    except Exception:
        # Observability must never cost the owner an answer they already
        # paid for. The answer is already computed by the time we get here.
        pass
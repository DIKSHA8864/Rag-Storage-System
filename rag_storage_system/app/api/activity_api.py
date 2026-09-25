"""
Owner-only view of the per-question log (llm_usage_log, written by
app/observability/usage_log.py) - Blueprint Work Plan M2: "log every
request - query, retrieved chunk IDs + scores, model, token usage,
latency, citation-check result - to Postgres for the owner's audit and
tuning". The rows were already recorded; this is the read side.
Always scoped to the caller's own organization.
"""

from fastapi import APIRouter, Depends, Query

from app.api.schemas import QueryLogEntry, QueryLogResponse
from app.security.auth import require_owner_role

router = APIRouter(prefix="/admin", tags=["activity"], dependencies=[Depends(require_owner_role)])


@router.get("/query-log", response_model=QueryLogResponse)
def query_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    questions_only: bool = True,
    owner: dict = Depends(require_owner_role),
) -> QueryLogResponse:
    from app.api import storage_api

    rows, total = storage_api.metadata_repository.list_llm_usage_log(
        owner["tenant_id"], limit=limit, offset=offset, questions_only=questions_only
    )

    entries = []
    for row in rows:
        scores = [float(s) for s in row["retrieved_chunk_scores"] if s is not None]
        entries.append(
            QueryLogEntry(
                id=row["id"],
                created_at=str(row["created_at"]),
                purpose=row["purpose"],
                query_text=row.get("query_text"),
                model=row["model"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                latency_ms=row["latency_ms"],
                citation_check_result=row.get("citation_check_result"),
                retrieved_count=len(row["retrieved_chunk_ids"]),
                top_score=max(scores) if scores else None,
                matter_id=row.get("matter_id"),
            )
        )
    return QueryLogResponse(entries=entries, total=total)

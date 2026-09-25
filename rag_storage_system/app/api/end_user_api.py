"""
End User API - text query and document comparison, for an actual End
User (not the Owner/Admin). Authenticated with X-End-User-Key against
END_USER_API_KEY (config/settings.py, app/security/auth.py) - a
different secret in a different header from the Owner/Admin API's
X-API-Key, so an End User can never reach /categories, /documents,
/process, or POST /search (the Owner/Admin search endpoint) and an
Admin key presented here is simply the wrong credential. See
app/security/auth.py's module docstring for why that's enough to
guarantee the separation without real per-user RBAC.

Endpoints:
    POST /end-user/query     plain Q&A - hybrid retrieval, same
                              pipeline as POST /search, scoped to this
                              key instead
    POST /end-user/compare   submit text OR a PDF/DOCX/TXT file
                              (Phase 2 - audio/video is Phase 3) and
                              get back a full structured comparison
                              report against the knowledge base (see
                              app/analysis/)
    POST /end-user/compare/export
                              same comparison as /compare, returned as
                              a downloadable .docx/.pdf file instead of
                              JSON, always ending with the Owner's
                              current disclaimer (app/disclaimer.py,
                              app/analysis/report_export.py)

Nothing an End User submits to /compare is ever persisted to protected
storage, the metadata database, or pgvector - it exists only for the
duration of one request (see app/analysis/ingestion.py).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile

from app.security.virus_scan import ScannerUnavailable, scan_bytes
from app.analysis.ingestion import is_supported_submission, process_submission, process_text_submission
from app.analysis.report_builder import build_analysis_report
from app.analysis.report_export import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    build_report_docx,
    build_report_pdf,
)
from app.api.schemas import (
    AnalysisReport,
    EndUserQueryRequest,
    EndUserQueryResponse,
    EndUserQueryResultChunk,
    ThreadCreateRequest,
    ThreadInfo,
    ThreadListResponse,
    ThreadMessageInfo,
    ThreadMessagesResponse,
)
from app.disclaimer import get_current_disclaimer_text
from app.retrieval.retriever import retrieve, retrieve_for_matter
from app.security.auth import current_matter as _current_matter
from app.security.auth import require_end_user_key
from app.security.rate_limit import limiter
from config.settings import get_settings
import json

from fastapi.responses import StreamingResponse

from app.analysis.answer_generation import stream_grounded_answer
from app.billing import get_billing_service
from app.billing.service import RESOURCE_LLM_CALLS, PlanLimitExceededError
from app.retrieval_settings import get_current_retrieval_settings

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/end-user",
    tags=["end-user"],
    dependencies=[Depends(require_end_user_key)],
)


@router.post("/query", response_model=EndUserQueryResponse)
@limiter.limit("30/minute")
def end_user_query(request: Request, body: EndUserQueryRequest, matter: dict = Depends(_current_matter)) -> EndUserQueryResponse:
    """
    Ask a question against the knowledge base and get back the most
    relevant chunks (same hybrid retrieval pipeline as POST /search -
    app/retrieval/retriever.py), scoped to the End User key.

    Top K is the Owner-configured Retrieval Settings value
    (GET/PUT /admin/retrieval-settings) unless `top_k` is explicitly
    passed in this request, which overrides it for this call only.
    """

    resolved_top_k = body.top_k
    if resolved_top_k is None:
        resolved_top_k = _current_retrieval_settings(matter["tenant_id"]).top_k

    if body.category is not None:
        results = retrieve(body.query, top_k=resolved_top_k, category=body.category, tenant_id=matter["tenant_id"])
    else:
        results = retrieve_for_matter(
            body.query, matter["id"], top_k=resolved_top_k, tenant_id=matter["tenant_id"]
        )

    return EndUserQueryResponse(
        query=body.query,
        results=[
            EndUserQueryResultChunk(
                chunk_text=result["chunk_text"],
                filename=result["filename"],
                category=result["category"],
                chapter=result.get("chapter"),
                section=result.get("section"),
                start_page=result.get("start_page"),
                end_page=result.get("end_page"),
                score=result["final_score"],
            )
            for result in results
        ],
    )


def _enforce_llm_usage_limit(tenant_id: int) -> None:
    """Raise HTTP 402 Payment Required if this tenant's plan's LLM-call limit for the current billing period is already reached - see app/billing/service.py's check_limit()."""

    from app.api import storage_api

    try:
        get_billing_service(storage_api.metadata_repository).check_limit(tenant_id, RESOURCE_LLM_CALLS)
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))


async def _resolve_input_chunks(query: Optional[str], file: Optional[UploadFile]) -> list[dict]:
    """
    Shared by /compare and /compare/export: exactly one of `query`
    (pasted text) or `file` (a PDF/DOCX/TXT upload) - not both, not
    neither. Nothing submitted here is stored; it's processed once and
    discarded.
    """

    if (query is None) == (file is None):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of `query` (text) or `file` (upload)."
        )

    if query is not None:
        return process_text_submission(query)

    filename = file.filename or "submission"

    if not is_supported_submission(filename):
        allowed = ", ".join(sorted(get_settings().allowed_extensions_set))
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type for '{filename}'. Supported: {allowed}. "
                "Audio/video input is not yet supported."
            ),
        )

    data = await file.read()
    await file.close()

    try:
        verdict = scan_bytes(data)
    except ScannerUnavailable:
        raise HTTPException(status_code=503, detail="The file couldn't be checked for viruses right now - try again later.")
    if not verdict.clean:
        raise HTTPException(status_code=400, detail="This file appears to contain a virus and was not processed.")
    return process_submission(filename, data)
def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _current_retrieval_settings(tenant_id: int):
    """Deferred import - see _current_disclaimer_text()'s docstring for why."""

    from app.api import storage_api

    return get_current_retrieval_settings(storage_api.metadata_repository, tenant_id=tenant_id)


@router.post("/threads", response_model=ThreadInfo)
def create_thread(request: ThreadCreateRequest, matter: dict = Depends(_current_matter)) -> ThreadInfo:
    """Start a new conversation thread, scoped to the caller's Matter."""

    from app.api import storage_api

    thread = storage_api.metadata_repository.create_thread(matter["id"], request.title)

    return ThreadInfo(
        id=thread["id"],
        matter_id=thread["matter_id"],
        title=thread["title"],
        created_at=str(thread["created_at"]),
        updated_at=str(thread["updated_at"]),
    )


@router.get("/threads", response_model=ThreadListResponse)
def list_threads(matter: dict = Depends(_current_matter)) -> ThreadListResponse:
    """List every thread belonging to the caller's Matter - never another Matter's."""

    from app.api import storage_api

    threads = storage_api.metadata_repository.list_threads(matter["id"])

    return ThreadListResponse(
        threads=[
            ThreadInfo(
                id=t["id"],
                matter_id=t["matter_id"],
                title=t["title"],
                created_at=str(t["created_at"]),
                updated_at=str(t["updated_at"]),
            )
            for t in threads
        ]
    )


@router.get("/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
def get_thread_messages(thread_id: int, matter: dict = Depends(_current_matter)) -> ThreadMessagesResponse:
    """
    Full message history for one thread. 404s (not another Matter's
    data leaking through) for a thread_id that exists but belongs to
    a different Matter - see get_thread()'s isolation check.
    """

    from app.api import storage_api

    thread = storage_api.metadata_repository.get_thread(thread_id, matter["id"])
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    messages = storage_api.metadata_repository.list_thread_messages(thread_id)

    return ThreadMessagesResponse(
        thread_id=thread_id,
        messages=[
            ThreadMessageInfo(
                id=m["id"],
                thread_id=m["thread_id"],
                role=m["role"],
                content=m["content"],
                sources=json.loads(m["sources_json"]) if m["sources_json"] else [],
                created_at=str(m["created_at"]),
            )
            for m in messages
        ],
    )


async def _stream_query_answer(
    query: str,
    top_k: Optional[int],
    category: Optional[str],
    matter: dict,
    thread_id: Optional[int],
):
    from app.api import storage_api

    repo = storage_api.metadata_repository

    if thread_id is not None and repo.get_thread(thread_id, matter["id"]) is None:
        yield _sse_event("error", {"detail": "Thread not found."})
        yield _sse_event("done", {})
        return

    settings = _current_retrieval_settings(matter["tenant_id"])
    resolved_top_k = top_k if top_k is not None else settings.top_k

    # The 200 status line is already sent by the time this generator
    # runs, so a retrieval failure (database/embedding model unreachable)
    # can't become an HTTP error anymore - it must be an explicit "error"
    # event. Otherwise the stream just ends, and a client can't tell an
    # outage apart from an honest "the library has nothing on this".
    try:
        results = retrieve(
            query,
            top_k=resolved_top_k,
            category=category,
            score_threshold=settings.score_threshold,
            tenant_id=matter["tenant_id"],
        )
    except Exception:
        logger.exception("Retrieval failed for an end-user query")
        yield _sse_event("error", {"detail": "The library search is unavailable right now. Please try again shortly."})
        yield _sse_event("done", {})
        return

    if thread_id is not None:
        repo.add_thread_message(thread_id, "user", query)

    # Honest-gap check, citation-locked sources, and the actual
    # Claude-or-template answer are all the one shared implementation
    # (app/analysis/answer_generation.py's stream_grounded_answer()) -
    # also used by the Owner-scope POST /research/ask - so the two
    # scopes can never behave differently here.
    sources_payload: list[dict] = []
    answer_pieces: list[str] = []

    async for event, payload in stream_grounded_answer(
        query, results, settings.min_chunks, purpose="end_user_query", matter_id=matter["id"] or None,
        tenant_id=matter["tenant_id"],
    ):
        if event == "sources":
            sources_payload = payload["sources"]
        elif event == "answer_chunk":
            answer_pieces.append(payload["text"])
        yield _sse_event(event, payload)

    if thread_id is not None:
        repo.add_thread_message(
            thread_id, "assistant", "".join(answer_pieces), json.dumps(sources_payload, ensure_ascii=False)
        )


@router.post("/query/stream")
async def end_user_query_stream(
    request: EndUserQueryRequest,
    matter: dict = Depends(_current_matter),
) -> StreamingResponse:
    """
    Same retrieval as POST /end-user/query, but streams the generated
    answer gradually as Server-Sent Events instead of returning
    everything at once - see app/analysis/answer_generation.py.

    Citations are LOCKED before any answer text streams: the `sources`
    event is always the first one sent, built from the one retrieval
    call this request makes - the answer text streamed afterward is
    generated only from that same fixed chunk set, so what's cited
    always matches what actually produced the answer.

    Pass `thread_id` (from POST /end-user/threads) to append this Q&A
    turn to an existing thread - it must belong to the caller's own
    Matter, or this 404s via an "error" event rather than leaking or
    writing into someone else's conversation.

    Event types: "sources" (once, first), "answer_chunk" (0+, in
    order), "error" (0-1, on a generation failure or an unknown/
    foreign thread_id), "done" (once, always last).
    """

    _enforce_llm_usage_limit(matter["tenant_id"])

    return StreamingResponse(
        _stream_query_answer(request.query, request.top_k, request.category, matter, request.thread_id),
        media_type="text/event-stream",
    )

def _current_disclaimer_text(tenant_id: int) -> str:
    """
    Deferred import to avoid a circular import: app/api/storage_api.py
    itself imports this router at the bottom of its module, so
    end_user_api.py can't import storage_api at module load time -
    only once storage_api is fully loaded, i.e. lazily, inside a
    request. Reading storage_api.metadata_repository (rather than
    calling app.metadata.get_metadata_repository() directly) matters
    for tests: they monkeypatch that attribute to a throwaway SQLite
    repository, and this must see the same one.
    """

    from app.api import storage_api

    return get_current_disclaimer_text(storage_api.metadata_repository, tenant_id=tenant_id)


@router.post("/compare", response_model=AnalysisReport)
async def end_user_compare(
    query: Optional[str] = Form(None, description="Pasted text to compare, instead of a file."),
    file: Optional[UploadFile] = File(None, description="A PDF/DOCX/TXT file to compare."),
    category: Optional[str] = Form(None, description="Restrict comparison to one knowledge-base category."),
    matter: dict = Depends(_current_matter),
) -> AnalysisReport:
    """
    Compare submitted text or a document against the knowledge base
    and return a full structured analysis report: executive summary,
    overall match score, detailed matching (similarities/differences/
    gaps/conflicts), recommendations, and cited sources for every
    claim (see app/analysis/report_builder.py). Scoped to the caller's
    tenant, same as every other retrieval path.
    """

    input_chunks = await _resolve_input_chunks(query, file)

    if not input_chunks:
        raise HTTPException(
            status_code=400, detail="No extractable text found in the submission."
        )

    _enforce_llm_usage_limit(matter["tenant_id"])
    report = build_analysis_report(input_chunks, category=category, tenant_id=matter["tenant_id"])

    return AnalysisReport(**report)


@router.post("/compare/export")
async def end_user_compare_export(
    format: str = Form(..., description="'docx' or 'pdf'."),
    query: Optional[str] = Form(None, description="Pasted text to compare, instead of a file."),
    file: Optional[UploadFile] = File(None, description="A PDF/DOCX/TXT file to compare."),
    category: Optional[str] = Form(None, description="Restrict comparison to one knowledge-base category."),
    matter: dict = Depends(_current_matter),
) -> Response:
    """
    Same comparison as POST /compare, returned as a downloadable
    .docx/.pdf file instead of JSON - always ending with the Owner's
    current disclaimer (GET/PUT /admin/disclaimer,
    app/analysis/report_export.py), so an Owner's edit shows up in the
    very next export.
    """

    if format not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="`format` must be 'docx' or 'pdf'.")

    input_chunks = await _resolve_input_chunks(query, file)

    if not input_chunks:
        raise HTTPException(
            status_code=400, detail="No extractable text found in the submission."
        )

    _enforce_llm_usage_limit(matter["tenant_id"])
    report = build_analysis_report(input_chunks, category=category, tenant_id=matter["tenant_id"])
    disclaimer_text = _current_disclaimer_text(matter["tenant_id"])

    if format == "docx":
        content = build_report_docx(report, disclaimer_text)
        media_type = DOCX_MEDIA_TYPE
        filename = "analysis_report.docx"
    else:
        content = build_report_pdf(report, disclaimer_text)
        media_type = PDF_MEDIA_TYPE
        filename = "analysis_report.pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

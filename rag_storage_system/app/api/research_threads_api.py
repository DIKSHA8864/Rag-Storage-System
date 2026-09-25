"""
Owner research threads and streaming answers (Blueprint Work Plan M3:
"Chat UI over /ask with streaming responses ... Threads persisted; any
thread or answer exports via the document service as .docx/.pdf memo").

A thread belongs to the admin user who started it (their login's `sub`)
within their organization - nobody else, not even another admin of the
same firm, can read, rename, export, or add to it.

POST /research/ask/stream runs exactly the same retrieval and
citation-locked answer generation as POST /research/ask
(app/analysis/answer_generation.py's stream_grounded_answer()), streamed
as Server-Sent Events, and saves the question + answer + its locked
sources to the thread once the answer completes. The existing
non-streaming POST /research/ask and /research/export are unchanged.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.analysis.answer_generation import stream_grounded_answer
from app.analysis.report_export import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE, build_research_memo_docx, build_research_memo_pdf
from app.api.schemas import (
    MessageResponse,
    ResearchMessageInfo,
    ResearchStreamRequest,
    ResearchThreadCreateRequest,
    ResearchThreadDetailResponse,
    ResearchThreadExportRequest,
    ResearchThreadInfo,
    ResearchThreadListResponse,
    ResearchThreadRenameRequest,
)
from app.billing.service import RESOURCE_LLM_CALLS
from app.disclaimer import get_current_disclaimer_text
from app.retrieval_settings import get_current_retrieval_settings
from app.security.auth import require_admin_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/research", tags=["research-threads"])

_TITLE_CHARS = 80


def _identity(owner: dict | None) -> tuple[int, str]:
    """(tenant_id, owner_sub) - threads need a signed-in admin, not the legacy shared key."""

    if not owner or not owner.get("sub"):
        raise HTTPException(status_code=403, detail="Sign in with your own account to use saved research threads.")
    return owner["tenant_id"], str(owner["sub"])


def _repo():
    # Deferred: storage_api imports this module (and tests swap its repository).
    from app.api import storage_api

    return storage_api.metadata_repository


def _thread_info(row: dict, message_count: int | None = None) -> ResearchThreadInfo:
    return ResearchThreadInfo(
        id=row["id"],
        title=row["title"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        message_count=row.get("message_count", message_count or 0),
    )


def _owned_thread(thread_id: int, owner: dict | None) -> dict:
    tenant_id, owner_sub = _identity(owner)
    thread = _repo().get_research_thread(thread_id, tenant_id, owner_sub)
    if thread is None:
        raise HTTPException(status_code=404, detail="Research thread not found.")
    return thread


def _title_from(query: str) -> str:
    title = " ".join(query.split())
    return title if len(title) <= _TITLE_CHARS else title[: _TITLE_CHARS - 3].rsplit(" ", 1)[0] + "..."


@router.get("/threads", response_model=ResearchThreadListResponse)
def list_threads(owner: dict | None = Depends(require_admin_key)) -> ResearchThreadListResponse:
    tenant_id, owner_sub = _identity(owner)
    return ResearchThreadListResponse(
        threads=[_thread_info(row) for row in _repo().list_research_threads(tenant_id, owner_sub)]
    )


@router.post("/threads", response_model=ResearchThreadInfo)
def create_thread(
    request: ResearchThreadCreateRequest, owner: dict | None = Depends(require_admin_key)
) -> ResearchThreadInfo:
    tenant_id, owner_sub = _identity(owner)
    title = (request.title or "").strip() or "New research"
    return _thread_info(_repo().create_research_thread(tenant_id, owner_sub, title))


@router.get("/threads/{thread_id}", response_model=ResearchThreadDetailResponse)
def get_thread(thread_id: int, owner: dict | None = Depends(require_admin_key)) -> ResearchThreadDetailResponse:
    thread = _owned_thread(thread_id, owner)
    messages = _repo().list_research_messages(thread_id)
    return ResearchThreadDetailResponse(
        thread=_thread_info(thread, message_count=len(messages)),
        messages=[
            ResearchMessageInfo(
                id=m["id"], role=m["role"], content=m["content"], sources=m["sources"], created_at=str(m["created_at"])
            )
            for m in messages
        ],
    )


@router.patch("/threads/{thread_id}", response_model=ResearchThreadInfo)
def rename_thread(
    thread_id: int, request: ResearchThreadRenameRequest, owner: dict | None = Depends(require_admin_key)
) -> ResearchThreadInfo:
    tenant_id, owner_sub = _identity(owner)
    renamed = _repo().rename_research_thread(thread_id, tenant_id, owner_sub, request.title.strip())
    if renamed is None:
        raise HTTPException(status_code=404, detail="Research thread not found.")
    return _thread_info(renamed)


@router.delete("/threads/{thread_id}", response_model=MessageResponse)
def delete_thread(thread_id: int, owner: dict | None = Depends(require_admin_key)) -> MessageResponse:
    tenant_id, owner_sub = _identity(owner)
    if not _repo().delete_research_thread(thread_id, tenant_id, owner_sub):
        raise HTTPException(status_code=404, detail="Research thread not found.")
    return MessageResponse(message="Research thread deleted.")


@router.post("/threads/{thread_id}/export")
def export_thread(
    thread_id: int, request: ResearchThreadExportRequest, owner: dict | None = Depends(require_admin_key)
) -> Response:
    """The whole thread as one research memorandum - exactly the saved questions, answers, and sources."""

    thread = _owned_thread(thread_id, owner)
    messages = _repo().list_research_messages(thread_id)

    exchanges = []
    pending_question = None
    for message in messages:
        if message["role"] == "user":
            pending_question = message["content"]
        elif pending_question is not None:
            exchanges.append({"question": pending_question, "answer": message["content"], "sources": message["sources"]})
            pending_question = None
    if not exchanges:
        raise HTTPException(status_code=400, detail="This thread has no answers to export yet.")

    disclaimer = get_current_disclaimer_text(_repo(), tenant_id=thread["tenant_id"])
    prepared_by = owner.get("email") if owner else None
    if request.format == "docx":
        content, media_type = build_research_memo_docx(thread["title"], exchanges, disclaimer, prepared_by), DOCX_MEDIA_TYPE
    else:
        content, media_type = build_research_memo_pdf(thread["title"], exchanges, disclaimer, prepared_by), PDF_MEDIA_TYPE

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="research-memo-{thread_id}.{request.format}"'},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask/stream")
async def research_ask_stream(
    request: ResearchStreamRequest, owner: dict | None = Depends(require_admin_key)
) -> StreamingResponse:
    """
    Events, in order: "thread" ({thread_id, title} - the thread this Q&A
    is saved to, created from the question if none was given), "sources"
    (locked before any answer text), "answer_chunk"..., optional "error",
    "done". Saved to the thread only once the answer completes without
    an error.
    """

    from app.api import storage_api

    tenant_id, owner_sub = _identity(owner)
    storage_api._enforce_plan_limit(tenant_id, RESOURCE_LLM_CALLS)

    repo = _repo()
    if request.thread_id is not None:
        thread = _owned_thread(request.thread_id, owner)
    else:
        thread = repo.create_research_thread(tenant_id, owner_sub, _title_from(request.query))

    async def events():
        yield _sse("thread", {"thread_id": thread["id"], "title": thread["title"]})

        settings = get_current_retrieval_settings(repo, tenant_id=tenant_id)
        try:
            results = storage_api.retrieve(
                request.query,
                top_k=request.top_k if request.top_k is not None else settings.top_k,
                category=request.category,
                score_threshold=settings.score_threshold,
                tenant_id=tenant_id,
            )
        except Exception:
            logger.exception("Retrieval failed for an owner research question")
            yield _sse("error", {"detail": "The library search is unavailable right now. Please try again shortly."})
            yield _sse("done", {})
            return

        sources: list[dict] = []
        answer_pieces: list[str] = []
        failed = False
        async for event, payload in stream_grounded_answer(
            request.query, results, settings.min_chunks, purpose="owner_research", tenant_id=tenant_id
        ):
            if event == "sources":
                sources = payload["sources"]
            elif event == "answer_chunk":
                answer_pieces.append(payload["text"])
            elif event == "error":
                failed = True
            yield _sse(event, payload)

        if not failed:
            answer = "".join(answer_pieces).strip()
            if answer:
                repo.add_research_exchange(thread["id"], request.query, answer, sources)

    return StreamingResponse(events(), media_type="text/event-stream")

"""
Research Console API (Phase 2). Owner-only - every route carries
require_admin_key, which is JWT bearer auth (app/security/auth.py).

    POST   /ask                               ask the library
    GET    /research/threads                  list saved threads
    GET    /research/threads/{id}             one thread + its messages
    DELETE /research/threads/{id}             delete a thread
    GET    /research/prompt                   the active system prompt
    GET    /research/prompt/versions          full version history
    POST   /research/prompt                   save a new version (activates it)
    POST   /research/prompt/{version}/activate  roll back to a version
    GET    /research/threads/{id}/export.docx  research memo, .docx
    GET    /research/threads/{id}/export.pdf   research memo, .pdf

This module is thin on purpose: it authenticates, calls
app/research/, persists, and serializes. Every rule that the Blueprint
fixes lives one layer down, where the acceptance tests can reach it
without going through HTTP.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    AskRequest,
    AskResponse,
    SystemPromptListResponse,
    SystemPromptResponse,
    SystemPromptUpdateRequest,
    ThreadDetailResponse,
    ThreadListResponse,
)
from app.docgen import build_memo_docx, build_memo_pdf
from app.docgen.memo_builder import default_memo
from app.research import prompts, query_log, threads
from app.research.answer_service import answer_question
from app.security.audit_log import log_audit_event
from app.security.auth import require_admin_key
from config.settings import get_settings

router = APIRouter(tags=["Research Console"])


def _owner_id(claims: dict) -> int:
    return int(claims["sub"])


# ----------------------------------------------------------------------
# POST /ask
# ----------------------------------------------------------------------

@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, claims: dict = Depends(require_admin_key)) -> AskResponse:
    """
    Ask the private library a legal question.

    A low-confidence question returns 200 with
    citation_status="not_in_library" - refusing is a correct answer,
    not an error, so it is not a 4xx.
    """

    owner_id = _owner_id(claims)

    try:
        result = answer_question(
            request.question,
            category=request.category,
        )
    except RuntimeError as exc:
        # Missing ANTHROPIC_API_KEY, or the Anthropic client failing to
        # construct - a configuration problem, not a bad request.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    thread_id = request.thread_id

    if request.save:
        if thread_id is None:
            title = request.question.strip()[:80]
            thread_id = threads.create_thread(owner_id, title)["id"]
        elif threads.get_thread(thread_id, owner_id) is None:
            raise HTTPException(status_code=404, detail="Thread not found.")

        threads.append_exchange(
            thread_id,
            question=request.question,
            answer=result.answer,
            sources=result.sources,
            citation_status=result.status,
            citation_detail=result.citation_detail,
        )

    query_log.log_ask(
        result,
        query=request.question,
        owner_id=owner_id,
        thread_id=thread_id,
        category=request.category,
    )

    # A stripped citation is a citation-lock violation that reached an
    # answer - it belongs in the human-readable audit trail too, not
    # only in ask_query_logs.
    if result.status == "stripped":
        log_audit_event(
            "citation_violation",
            category=request.category or "-",
            filename="-",
            status="stripped",
            detail=str(result.citation_detail.get("unsupported_authorities", [])),
        )

    return AskResponse(
        question=request.question,
        answer=result.answer,
        citation_status=result.status,
        insufficient_authority=result.insufficient_authority,
        sources=result.sources,
        top_score=result.top_score,
        thread_id=thread_id if request.save else None,
        model=result.model,
        prompt_version=result.prompt_version,
        latency_ms=result.latency_ms,
        citation_detail=result.citation_detail,
    )


# ----------------------------------------------------------------------
# Threads
# ----------------------------------------------------------------------

@router.get("/research/threads", response_model=ThreadListResponse)
def list_threads(claims: dict = Depends(require_admin_key),
                 limit: int = Query(50, ge=1, le=200)) -> ThreadListResponse:
    return ThreadListResponse(threads=threads.list_threads(_owner_id(claims), limit=limit))


@router.get("/research/threads/{thread_id}", response_model=ThreadDetailResponse)
def get_thread(thread_id: int, claims: dict = Depends(require_admin_key)) -> ThreadDetailResponse:
    thread = threads.get_thread(thread_id, _owner_id(claims))

    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    return ThreadDetailResponse(**thread)


@router.delete("/research/threads/{thread_id}")
def delete_thread(thread_id: int, claims: dict = Depends(require_admin_key)) -> dict:
    if not threads.delete_thread(thread_id, _owner_id(claims)):
        raise HTTPException(status_code=404, detail="Thread not found.")

    return {"message": f"Thread {thread_id} deleted."}


# ----------------------------------------------------------------------
# Prompt management
# ----------------------------------------------------------------------

@router.get("/research/prompt", response_model=SystemPromptResponse)
def get_prompt(_: dict = Depends(require_admin_key)) -> SystemPromptResponse:
    return SystemPromptResponse(**prompts.get_active_prompt(), is_active=True)


@router.get("/research/prompt/versions", response_model=SystemPromptListResponse)
def get_prompt_versions(_: dict = Depends(require_admin_key)) -> SystemPromptListResponse:
    return SystemPromptListResponse(versions=prompts.list_versions())


@router.post("/research/prompt", response_model=SystemPromptResponse)
def update_prompt(request: SystemPromptUpdateRequest,
                  claims: dict = Depends(require_admin_key)) -> SystemPromptResponse:
    """
    Save a new version and activate it. The previous version is kept -
    prompts are never edited in place (see app/research/prompts.py).
    """

    try:
        saved = prompts.save_new_version(
            request.content, created_by=claims.get("email", "owner")
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    log_audit_event(
        "system_prompt_updated", category="-", filename="-",
        status="ok", detail=f"version {saved['version']}",
    )

    return SystemPromptResponse(**saved, is_active=True)


@router.post("/research/prompt/{version}/activate", response_model=SystemPromptResponse)
def rollback_prompt(version: int, _: dict = Depends(require_admin_key)) -> SystemPromptResponse:
    try:
        activated = prompts.activate_version(version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    log_audit_event(
        "system_prompt_rollback", category="-", filename="-",
        status="ok", detail=f"version {version}",
    )

    return SystemPromptResponse(**activated, is_active=True)


# ----------------------------------------------------------------------
# Export (the "ready file" rule)
# ----------------------------------------------------------------------

def _thread_to_memo(thread: dict, owner_email: str) -> dict:
    """
    Turn a stored thread into the docgen memo spec. Only answers that
    actually carry authority become memo entries - a "not in the
    library" refusal is a true answer on screen but not something to
    print as a research memo.
    """

    entries = []
    pending_question = None

    for message in thread["messages"]:
        if message["role"] == "question":
            pending_question = message["content"]
        elif pending_question is not None:
            if message.get("citation_status") != "not_in_library":
                entries.append({
                    "question": pending_question,
                    "analysis": message["content"],
                    "sources": message.get("sources") or [],
                })
            pending_question = None

    if not entries:
        raise HTTPException(
            status_code=400,
            detail="This thread has no cited answers to export.",
        )

    return default_memo(
        title=thread["title"],
        prepared_for=owner_email,
        entries=entries,
        disclaimer=get_settings().memo_disclaimer,
    )


def _safe_filename(title: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    return (keep.strip().replace(" ", "_") or "research_memo")[:60]


@router.get("/research/threads/{thread_id}/export.docx")
def export_docx(thread_id: int, claims: dict = Depends(require_admin_key)):
    thread = threads.get_thread(thread_id, _owner_id(claims))

    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    memo = _thread_to_memo(thread, claims.get("email", "the Owner"))
    name = _safe_filename(thread["title"])

    return StreamingResponse(
        iter([build_memo_docx(memo)]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'},
    )


@router.get("/research/threads/{thread_id}/export.pdf")
def export_pdf(thread_id: int, claims: dict = Depends(require_admin_key)):
    thread = threads.get_thread(thread_id, _owner_id(claims))

    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    memo = _thread_to_memo(thread, claims.get("email", "the Owner"))
    name = _safe_filename(thread["title"])

    return StreamingResponse(
        iter([build_memo_pdf(memo)]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )
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

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

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
)
from app.disclaimer import get_current_disclaimer_text
from app.retrieval.retriever import retrieve
from app.security.auth import require_end_user_key
from config.settings import get_settings
import json

from fastapi.responses import StreamingResponse

from app.analysis.answer_generator import generate_answer_stream
from app.retrieval_settings import get_current_retrieval_settings
router = APIRouter(
    prefix="/end-user",
    tags=["end-user"],
    dependencies=[Depends(require_end_user_key)],
)


@router.post("/query", response_model=EndUserQueryResponse)
def end_user_query(request: EndUserQueryRequest) -> EndUserQueryResponse:
    """
    Ask a question against the knowledge base and get back the most
    relevant chunks (same hybrid retrieval pipeline as POST /search -
    app/retrieval/retriever.py), scoped to the End User key.
    """

    results = retrieve(request.query, top_k=request.top_k, category=request.category)

    return EndUserQueryResponse(
        query=request.query,
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
    return process_submission(filename, data)
def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _current_retrieval_settings():
    """Deferred import - see _current_disclaimer_text()'s docstring for why."""

    from app.api import storage_api

    return get_current_retrieval_settings(storage_api.metadata_repository)


async def _stream_query_answer(query: str, top_k: Optional[int], category: Optional[str]):
    settings = _current_retrieval_settings()
    resolved_top_k = top_k if top_k is not None else settings.top_k

    results = retrieve(
        query,
        top_k=resolved_top_k,
        category=category,
        score_threshold=settings.score_threshold,
    )

    if len(results) < settings.min_chunks:
        yield _sse_event("sources", {"sources": []})
        yield _sse_event(
            "answer_chunk",
            {"text": "Insufficient information found in the available knowledge base."},
        )
        yield _sse_event("done", {})
        return

    # CITATION LOCK: built once, from this exact `results` list, and
    # sent before a single answer token exists. Nothing after this
    # point can change it - generate_answer_stream() is only ever
    # given this same, already-fixed chunk list.
    sources = [
        {
            "filename": r["filename"],
            "category": r["category"],
            "section": r.get("section"),
            "start_page": r.get("start_page"),
            "end_page": r.get("end_page"),
            "score": r["final_score"],
        }
        for r in results
    ]
    yield _sse_event("sources", {"sources": sources})

    try:
        async for piece in generate_answer_stream(query, results):
            yield _sse_event("answer_chunk", {"text": piece})
    except Exception as exc:
        yield _sse_event("error", {"detail": str(exc)})

    yield _sse_event("done", {})


@router.post("/query/stream")
async def end_user_query_stream(request: EndUserQueryRequest) -> StreamingResponse:
    """
    Same retrieval as POST /end-user/query, but streams the generated
    answer gradually as Server-Sent Events instead of returning
    everything at once - see app/analysis/answer_generator.py.

    Citations are LOCKED before any answer text streams: the `sources`
    event is always the first one sent, built from the one retrieval
    call this request makes - the answer text streamed afterward is
    generated only from that same fixed chunk set, so what's cited
    always matches what actually produced the answer.

    Event types: "sources" (once, first), "answer_chunk" (0+, in
    order), "error" (0-1, only on a generation failure), "done" (once,
    always last).
    """

    return StreamingResponse(
        _stream_query_answer(request.query, request.top_k, request.category),
        media_type="text/event-stream",
    )

def _current_disclaimer_text() -> str:
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

    return get_current_disclaimer_text(storage_api.metadata_repository)


@router.post("/compare", response_model=AnalysisReport)
async def end_user_compare(
    query: Optional[str] = Form(None, description="Pasted text to compare, instead of a file."),
    file: Optional[UploadFile] = File(None, description="A PDF/DOCX/TXT file to compare."),
    category: Optional[str] = Form(None, description="Restrict comparison to one knowledge-base category."),
) -> AnalysisReport:
    """
    Compare submitted text or a document against the knowledge base
    and return a full structured analysis report: executive summary,
    overall match score, detailed matching (similarities/differences/
    gaps/conflicts), recommendations, and cited sources for every
    claim (see app/analysis/report_builder.py).
    """

    input_chunks = await _resolve_input_chunks(query, file)

    if not input_chunks:
        raise HTTPException(
            status_code=400, detail="No extractable text found in the submission."
        )

    report = build_analysis_report(input_chunks, category=category)

    return AnalysisReport(**report)


@router.post("/compare/export")
async def end_user_compare_export(
    format: str = Form(..., description="'docx' or 'pdf'."),
    query: Optional[str] = Form(None, description="Pasted text to compare, instead of a file."),
    file: Optional[UploadFile] = File(None, description="A PDF/DOCX/TXT file to compare."),
    category: Optional[str] = Form(None, description="Restrict comparison to one knowledge-base category."),
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

    report = build_analysis_report(input_chunks, category=category)
    disclaimer_text = _current_disclaimer_text()

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

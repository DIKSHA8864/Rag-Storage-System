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

Nothing an End User submits to /compare is ever persisted to protected
storage, the metadata database, or pgvector - it exists only for the
duration of one request (see app/analysis/ingestion.py).
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.analysis.ingestion import is_supported_submission, process_submission, process_text_submission
from app.analysis.report_builder import build_analysis_report
from app.api.schemas import (
    AnalysisReport,
    EndUserQueryRequest,
    EndUserQueryResponse,
    EndUserQueryResultChunk,
)
from app.retrieval.retriever import retrieve
from app.security.auth import require_end_user_key
from config.settings import get_settings

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

    Pass exactly one of `query` (pasted text) or `file` (a PDF/DOCX/TXT
    upload) - not both, not neither. Nothing submitted here is stored;
    it's processed once, compared, and discarded.
    """

    if (query is None) == (file is None):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of `query` (text) or `file` (upload)."
        )

    if query is not None:
        input_chunks = process_text_submission(query)
    else:
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
        input_chunks = process_submission(filename, data)

    if not input_chunks:
        raise HTTPException(
            status_code=400, detail="No extractable text found in the submission."
        )

    report = build_analysis_report(input_chunks, category=category)

    return AnalysisReport(**report)

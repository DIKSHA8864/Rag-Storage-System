"""
Complaint Generator / Lifecycle Drafting API - attorney/paralegal
tooling, Owner-JWT scoped (not the Client's own X-End-User-Key: drafting
a pleading is firm work product, not something the Client does
themselves), gated by role-based Matter access
(app/security/auth.py's ensure_matter_access()).

Endpoints:
    POST /admin/causes-of-action                              curate a cause of action's elements/authority
    GET  /admin/causes-of-action                               list the curated library
    POST /admin/intake/sessions/{id}/complaint                 generate a draft complaint for selected causes of action
    GET  /admin/intake/sessions/{id}/complaints                list generated drafts for a session
    GET  /admin/complaints/{complaint_id}/download              download a generated draft
"""

import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.schemas import (
    CauseOfActionCreateRequest,
    CauseOfActionInfo,
    CauseOfActionListResponse,
    ComplaintGenerateRequest,
    ComplaintInfo,
)
from app.complaint.builder import build_complaint_draft
from app.complaint.docx_renderer import ComplaintDocxRenderer
from app.security.auth import ensure_matter_access, require_admin_key

router = APIRouter(prefix="/admin", tags=["complaint-generator"], dependencies=[Depends(require_admin_key)])

_RENDERERS = {"docx": ComplaintDocxRenderer}


def _cause_info(row: dict) -> CauseOfActionInfo:
    return CauseOfActionInfo(
        id=row["id"], category=row["category"], name=row["name"],
        elements=row["elements"], authority_citation=row["authority_citation"], created_at=str(row["created_at"]),
    )


@router.post("/causes-of-action", response_model=CauseOfActionInfo)
def create_cause_of_action(request: CauseOfActionCreateRequest, owner: dict = Depends(require_admin_key)) -> CauseOfActionInfo:
    """Curate one cause of action's legal elements and authority - Owner/attorney only, library-only source of truth for the Complaint Generator."""

    from app.api import storage_api

    row = storage_api.metadata_repository.create_cause_of_action(
        request.category, request.name, request.elements, request.authority_citation
    )
    return _cause_info(row)


@router.get("/causes-of-action", response_model=CauseOfActionListResponse)
def list_causes_of_action(category: str | None = None) -> CauseOfActionListResponse:
    from app.api import storage_api

    rows = storage_api.metadata_repository.list_causes_of_action(category)
    return CauseOfActionListResponse(causes_of_action=[_cause_info(r) for r in rows])


@router.post("/intake/sessions/{session_id}/complaint", response_model=ComplaintInfo)
def generate_complaint(
    session_id: int, request: ComplaintGenerateRequest, owner: dict = Depends(require_admin_key)
) -> ComplaintInfo:
    from app.api import storage_api
    from app.storage import get_intake_storage_backend

    repo = storage_api.metadata_repository
    session = repo.get_intake_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Intake session not found.")

    ensure_matter_access(owner, session["matter_id"], repo)

    renderer_cls = _RENDERERS.get(request.format)
    if renderer_cls is None:
        raise HTTPException(status_code=400, detail="`format` must be 'docx'.")

    matter = repo.get_matter(session["matter_id"])
    draft = build_complaint_draft(
        session_id, session["matter_id"], matter["name"] if matter else "Unknown Matter",
        request.cause_of_action_ids, repo,
    )

    renderer = renderer_cls()
    content = renderer.render(draft)

    storage_backend = get_intake_storage_backend()
    category = f"session_{session_id}/complaints"
    storage_backend.create_category(category)
    filename = f"complaint_{session_id}_{'_'.join(map(str, request.cause_of_action_ids))}.{renderer.file_extension}"
    stored = storage_backend.save(category, filename, io.BytesIO(content))

    complaint = repo.create_complaint(
        session_id, session["matter_id"], request.format, request.cause_of_action_ids,
        stored["category"], stored["stored_filename"],
    )
    repo.add_timeline_event(session_id, "complaint_generated", f"Draft complaint generated for causes of action {request.cause_of_action_ids}.")

    return ComplaintInfo(
        id=complaint["id"], intake_session_id=session_id, matter_id=session["matter_id"],
        format=complaint["format"], cause_of_action_ids=complaint["cause_of_action_ids"],
        created_at=str(complaint["created_at"]),
    )


@router.get("/complaints/{complaint_id}/download")
def download_complaint(complaint_id: int, owner: dict = Depends(require_admin_key)) -> Response:
    from app.api import storage_api
    from app.storage import get_intake_storage_backend

    repo = storage_api.metadata_repository
    complaint = repo.get_complaint(complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found.")

    ensure_matter_access(owner, complaint["matter_id"], repo)

    storage_backend = get_intake_storage_backend()
    with storage_backend.open_file(complaint["stored_category"], complaint["stored_filename"]) as f:
        content = f.read()

    return Response(
        content=content,
        media_type=_RENDERERS[complaint["format"]].media_type,
        headers={"Content-Disposition": f'attachment; filename="complaint_{complaint_id}.{complaint["format"]}"'},
    )
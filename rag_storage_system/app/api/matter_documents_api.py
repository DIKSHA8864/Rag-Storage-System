"""
An attorney's case documents for one matter (Blueprint Phase 4: "upload
the case's pleadings and orders"). Each file is virus-scanned, stored in
case storage (INTAKE_STORAGE_PATH, never the library), and indexed in the
background into that matter's own namespace ("matter-<id>"). From then on
that matter's research, reports and complaint drafts can cite it; nothing
outside the matter can.

Access is the same as every other matter endpoint (ensure_matter_access):
the organization's owner, or staff assigned to the matter.

    GET    /admin/matters/{id}/documents                   list, with indexing status
    POST   /admin/matters/{id}/documents                   upload (multipart: file, doc_type)
    GET    /admin/matters/{id}/documents/{doc}/download    the original file
    POST   /admin/matters/{id}/documents/{doc}/reindex     index again (e.g. after a failure)
    DELETE /admin/matters/{id}/documents/{doc}             remove file + its search chunks
"""

import hashlib
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.schemas import MatterDocumentInfo, MatterDocumentListResponse
from app.ingestion.file_validator import validate_file_object
from app.jobs.matter_documents import case_document_chunk_group, run_matter_document_job
from app.jobs.queue import get_job_queue
from app.security.audit_log import log_audit_event
from app.security.auth import ensure_matter_access, require_admin_key
from app.security.virus_scan import ScannerUnavailable, scan_bytes

router = APIRouter(prefix="/admin/matters", tags=["matter-documents"], dependencies=[Depends(require_admin_key)])

DOC_TYPES = ["pleading", "order", "motion", "discovery", "correspondence", "evidence", "other"]

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
}


def _info(row: dict) -> MatterDocumentInfo:
    return MatterDocumentInfo(
        id=row["id"], matter_id=row["matter_id"], doc_type=row["doc_type"], original_filename=row["original_filename"],
        size=row["size"], uploaded_by=row.get("uploaded_by"), status=row["status"], chunk_count=row["chunk_count"],
        error=row.get("error"), created_at=str(row["created_at"]),
    )


def _matter_or_404(repo, owner: dict, matter_id: int) -> dict:
    ensure_matter_access(owner, matter_id, repo)
    matter = repo.get_matter(matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    return matter


def _storage():
    from app.storage import get_intake_storage_backend

    return get_intake_storage_backend()


def _enqueue_indexing(repo, document_id: int, matter_id: int, storage_backend) -> None:
    from app.api import storage_api

    get_job_queue().enqueue(
        run_matter_document_job, document_id, matter_id, repo, storage_backend, storage_api.get_vector_store()
    )


@router.get("/{matter_id}/documents", response_model=MatterDocumentListResponse)
def list_case_documents(matter_id: int, owner: dict = Depends(require_admin_key)) -> MatterDocumentListResponse:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    _matter_or_404(repo, owner, matter_id)
    return MatterDocumentListResponse(
        documents=[_info(row) for row in repo.list_matter_documents(matter_id)], doc_types=DOC_TYPES
    )


@router.post("/{matter_id}/documents", response_model=MatterDocumentInfo)
async def upload_case_document(
    matter_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    owner: dict = Depends(require_admin_key),
) -> MatterDocumentInfo:
    from app.api import storage_api
    from app.billing.service import RESOURCE_STORAGE_BYTES

    repo = storage_api.metadata_repository
    matter = _matter_or_404(repo, owner, matter_id)
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"doc_type must be one of: {', '.join(DOC_TYPES)}.")

    filename = Path(file.filename or "document").name
    data = await file.read()
    await file.close()

    is_valid, reason = validate_file_object(filename, len(data))
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid file: {reason}")

    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = next((d for d in repo.list_matter_documents(matter_id) if d["sha256"] == sha256), None)
    if duplicate is not None:
        raise HTTPException(status_code=409, detail=f"This file is already in the matter as '{duplicate['original_filename']}'.")

    storage_api._enforce_plan_limit(matter["tenant_id"], RESOURCE_STORAGE_BYTES, requested_increment=len(data))

    storage_backend = _storage()
    category = f"matter_{matter_id}/case_documents"
    try:
        verdict = scan_bytes(data)
    except ScannerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"{exc} The file was not stored - try again later.")
    if not verdict.clean:
        storage_backend.quarantine(category, filename, io.BytesIO(data))
        log_audit_event("matter_document_upload", category=category, filename=filename, status="infected",
                        detail=verdict.signature, actor=owner.get("email"))
        raise HTTPException(status_code=400, detail=f"Virus detected ({verdict.signature}) - the file was not added.")

    storage_backend.create_category(category)
    stored = storage_backend.save(category, filename, io.BytesIO(data))
    document = repo.create_matter_document(
        matter["tenant_id"], matter_id, doc_type, filename, stored["category"], stored["stored_filename"],
        stored["size"], sha256, owner.get("email"),
    )
    log_audit_event("matter_document_upload", category=category, filename=stored["stored_filename"], status="success",
                    detail=doc_type, actor=owner.get("email"))

    _enqueue_indexing(repo, document["id"], matter_id, storage_backend)
    return _info(repo.get_matter_document(document["id"], matter_id))


@router.get("/{matter_id}/documents/{document_id}/download")
def download_case_document(matter_id: int, document_id: int, owner: dict = Depends(require_admin_key)) -> Response:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    _matter_or_404(repo, owner, matter_id)
    document = repo.get_matter_document(document_id, matter_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    with _storage().open_file(document["stored_category"], document["stored_filename"]) as f:
        content = f.read()
    extension = Path(document["original_filename"]).suffix.lower()
    safe_name = document["original_filename"].replace('"', "")
    return Response(
        content=content, media_type=_MEDIA_TYPES.get(extension, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.post("/{matter_id}/documents/{document_id}/reindex", response_model=MatterDocumentInfo)
def reindex_case_document(matter_id: int, document_id: int, owner: dict = Depends(require_admin_key)) -> MatterDocumentInfo:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    _matter_or_404(repo, owner, matter_id)
    if repo.get_matter_document(document_id, matter_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    repo.update_matter_document_status(document_id, "queued", 0, None)
    _enqueue_indexing(repo, document_id, matter_id, _storage())
    return _info(repo.get_matter_document(document_id, matter_id))


@router.delete("/{matter_id}/documents/{document_id}")
def delete_case_document(matter_id: int, document_id: int, owner: dict = Depends(require_admin_key)) -> dict:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    matter = _matter_or_404(repo, owner, matter_id)
    document = repo.get_matter_document(document_id, matter_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Out of search first - a deleted pleading must never be cited again.
    try:
        storage_api.get_vector_store().delete_matter_document_chunks(
            matter_id, case_document_chunk_group(matter_id, document_id), matter["tenant_id"]
        )
    except Exception:
        raise HTTPException(status_code=503, detail="The search index is unavailable - nothing was deleted. Try again.")

    try:
        _storage().delete(document["stored_category"], document["stored_filename"])
    except FileNotFoundError:
        pass
    repo.delete_matter_document(document_id, matter_id)
    log_audit_event("matter_document_delete", category=document["stored_category"], filename=document["stored_filename"],
                    status="success", actor=owner.get("email"))
    return {"deleted": True}

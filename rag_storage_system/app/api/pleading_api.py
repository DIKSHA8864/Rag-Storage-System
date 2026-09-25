"""
Pleading details and the firm's own Word templates (Blueprint Phase 4:
"California pleading format; the firm's own .docx templates"). Always
scoped to the caller's organization.

    GET  /admin/pleading-settings          attorney block + court details used on every pleading
    PUT  /admin/pleading-settings          (owner)
    GET  /admin/templates                  the organization's templates
    POST /admin/templates                  upload one (owner; multipart: name, file) - checked before it's kept
    GET  /admin/templates/{id}/download
    DELETE /admin/templates/{id}           (owner)
"""

import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.schemas import (
    DocumentTemplateInfo,
    DocumentTemplateListResponse,
    PleadingSettings,
    PleadingSettingsResponse,
)
from app.complaint.template_fill import KNOWN_PLACEHOLDERS, TemplateError, inspect_template
from app.security.audit_log import log_audit_event
from app.security.auth import require_admin_key, require_owner_role
from app.security.virus_scan import ScannerUnavailable, scan_bytes

router = APIRouter(prefix="/admin", tags=["pleadings"], dependencies=[Depends(require_admin_key)])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_TEMPLATE_BYTES = 10 * 1024 * 1024


def _repo():
    from app.api import storage_api

    return storage_api.metadata_repository


def _storage():
    from app.storage import get_intake_storage_backend

    return get_intake_storage_backend()


def _template_info(row: dict) -> DocumentTemplateInfo:
    return DocumentTemplateInfo(
        id=row["id"], name=row["name"], kind=row["kind"], original_filename=row["original_filename"],
        placeholders=list(row["placeholders"] or []), uploaded_by=row.get("uploaded_by"), created_at=str(row["created_at"]),
    )


@router.get("/pleading-settings", response_model=PleadingSettingsResponse)
def get_pleading_settings(owner: dict = Depends(require_admin_key)) -> PleadingSettingsResponse:
    row = _repo().get_pleading_settings(owner["tenant_id"]) or {}
    return PleadingSettingsResponse(
        **{field: row.get(field) or "" for field in PleadingSettings.model_fields},
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        updated_by=row.get("updated_by"),
    )


@router.put("/pleading-settings", response_model=PleadingSettingsResponse)
def save_pleading_settings(body: PleadingSettings, owner: dict = Depends(require_owner_role)) -> PleadingSettingsResponse:
    values = {field: (getattr(body, field) or "").strip() for field in PleadingSettings.model_fields}
    _repo().save_pleading_settings(owner["tenant_id"], values, owner.get("email"))
    return get_pleading_settings(owner)


@router.get("/templates", response_model=DocumentTemplateListResponse)
def list_templates(owner: dict = Depends(require_admin_key)) -> DocumentTemplateListResponse:
    return DocumentTemplateListResponse(
        templates=[_template_info(t) for t in _repo().list_document_templates(owner["tenant_id"], "complaint")],
        placeholders=list(KNOWN_PLACEHOLDERS),
    )


@router.post("/templates", response_model=DocumentTemplateInfo)
async def upload_template(
    name: str = Form(...), file: UploadFile = File(...), owner: dict = Depends(require_owner_role)
) -> DocumentTemplateInfo:
    filename = Path(file.filename or "template.docx").name
    data = await file.read()
    await file.close()

    name = name.strip()[:255]
    if not name:
        raise HTTPException(status_code=400, detail="Give the template a name.")
    if Path(filename).suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="Templates must be Word .docx files.")
    if not data or len(data) > MAX_TEMPLATE_BYTES:
        raise HTTPException(status_code=400, detail="The template must be a non-empty file of at most 10 MB.")

    try:
        verdict = scan_bytes(data)
    except ScannerUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"{exc} The template was not stored - try again later.")
    if not verdict.clean:
        raise HTTPException(status_code=400, detail=f"Virus detected ({verdict.signature}) - the template was not added.")

    try:
        placeholders = inspect_template(data)
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    storage = _storage()
    category = f"templates/tenant-{owner['tenant_id']}"
    storage.create_category(category)
    stored = storage.save(category, filename, io.BytesIO(data))
    row = _repo().create_document_template(
        owner["tenant_id"], name, "complaint", filename, stored["category"], stored["stored_filename"],
        placeholders, owner.get("email"),
    )
    log_audit_event("template_upload", category=category, filename=stored["stored_filename"], actor=owner.get("email"))
    return _template_info(row)


def _owned_template(template_id: int, owner: dict) -> dict:
    template = _repo().get_document_template(template_id, owner["tenant_id"])
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return template


def load_template_bytes(template: dict) -> bytes:
    with _storage().open_file(template["stored_category"], template["stored_filename"]) as f:
        return f.read()


@router.get("/templates/{template_id}/download")
def download_template(template_id: int, owner: dict = Depends(require_admin_key)) -> Response:
    template = _owned_template(template_id, owner)
    safe_name = template["original_filename"].replace('"', "")
    return Response(
        content=load_template_bytes(template), media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, owner: dict = Depends(require_owner_role)) -> dict:
    template = _owned_template(template_id, owner)
    _storage().delete(template["stored_category"], template["stored_filename"])
    _repo().delete_document_template(template_id, owner["tenant_id"])
    log_audit_event("template_delete", category=template["stored_category"], filename=template["stored_filename"],
                    actor=owner.get("email"))
    return {"deleted": True}

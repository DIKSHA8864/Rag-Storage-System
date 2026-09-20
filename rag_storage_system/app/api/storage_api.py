"""
Admin storage API.

This is the "controlled interface" described in the project
synopsis: the only supported way to get files into protected
storage, organize them into category folders, and run them through
extraction -> segmentation -> chunking -> embeddings. Nobody -
including a future backend - is expected to touch storage/originals,
storage/processed, storage/segments, storage/chunks or
storage/embeddings directly; they go through this API instead.

All file operations go through get_storage_backend() (see
app/storage/__init__.py) rather than touching shutil/pathlib
directly. Today that resolves to LocalStorageBackend (free, local
disk, used for the demo). When it's time to pay for S3 / Cloudflare
R2 / Azure Blob / Google Cloud Storage / MinIO, only
app/storage/__init__.py needs to change - every endpoint below stays
exactly as it is.

Endpoints:
    POST   /categories                                        create a category (folder), optionally nested via `parent`
    GET    /categories                                        list categories/subfolders
    PATCH  /categories/{category}                             rename/move a category (path may include subfolders)
    DELETE /categories/{category}                             delete a category
    POST   /categories/{category}/documents                   upload PDF/DOCX/TXT files
    POST   /categories/{category}/documents/batch             upload several files at once
    PUT    /categories/{category}/documents/{filename}        replace a file's contents
    DELETE /categories/{category}/documents/{filename}        delete a file
    GET    /documents                                         list stored documents (with processing status) - poll this while a job runs
    POST   /process                                           enqueue extraction -> segmentation -> chunking -> embeddings as a background job, returns immediately
    GET    /process/{job_id}                                  poll a background processing job's status/result
    POST   /search                                            hybrid retrieval (vector + keyword + metadata filter -> rerank) over indexed chunks
    GET    /upload-test                                       plain HTML page for manually testing multi-file batch upload

    POST   /end-user/query                                    (End User scope) Q&A over the knowledge base - see app/api/end_user_api.py
    POST   /end-user/compare                                  (End User scope) submit text/a document, get a full comparison report

`{category}` accepts nested paths, e.g. /categories/Contracts/2024
is a subfolder of Contracts.

Authentication: every endpoint above (except /end-user/*) requires an
`X-API-Key` header matching ADMIN_API_KEY (config/settings.py / .env
- see app/security/auth.py). GET /, GET /docs, GET /openapi.json and
GET /upload-test are exempt (the docs/schema routes so Swagger UI can
load at all before you've authorized; the upload-test page so it can
be opened in a browser - its own fetch() calls still send the key).
In Swagger UI, click "Authorize" and paste the key once; every
"Try it out" call then includes it automatically.

/end-user/* requires a SEPARATE `X-End-User-Key` header matching
END_USER_API_KEY instead - a different secret in a different header,
so this key never grants access to anything above it. See
app/api/end_user_api.py and app/security/auth.py.

Every upload, replace, delete, rename, and category deletion is
recorded to logs/audit.log (see app/security/audit_log.py).

Run locally for the free demo (no cloud storage required):
    uvicorn app.api.storage_api:app --reload
Then open http://127.0.0.1:8000/docs for an interactive upload UI -
no separate frontend needed, including for
POST /categories/{category}/documents/batch's multi-file field (see
the openapi() patch below for why that needed a small nudge).
GET /upload-test remains available too as a plain HTML fallback.
"""

import io
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from app.api.auth_api import router as auth_router
from app.api.schemas import (
    CategoryCreateRequest,
    CategoryInfo,
    CategoryListResponse,
    CategoryRenameRequest,
    DisclaimerResponse,
    DisclaimerUpdateRequest,
    DocumentInfo,
    DocumentListResponse,
    MatterCreateRequest,
    MatterCreatedResponse,
    MatterInfo,
    MatterListResponse,
    MessageResponse,
    ProcessQueuedResponse,
    ProcessResult,
    ProcessStatusResponse,
    PromptVersionCreateRequest,
    PromptVersionInfo,
    PromptVersionListResponse,
    RetrievalSettingsResponse,
    RetrievalSettingsUpdateRequest,
    SearchRequest,
    SearchResponse,
    SearchResultChunk,
    UploadedFileResult,
    UploadResponse,
)
from app.disclaimer import DEFAULT_DISCLAIMER_TEXT
from app.ingestion.file_validator import validate_file_object
from app.jobs.processing import run_processing_job
from app.jobs.queue import get_job_queue
from app.metadata import get_metadata_repository
from app.metadata.models import DocumentStatus
from app.retrieval.retriever import retrieve
from app.retrieval_settings import DEFAULT_MIN_CHUNKS, DEFAULT_SCORE_THRESHOLD, DEFAULT_TOP_K
from app.security.audit_log import log_audit_event
from app.security.auth import hash_api_key, require_admin_key
from app.security.path_security import sanitize_category_path, sanitize_path_segment
from app.storage import get_storage_backend
from app.vector_store import get_vector_store

storage_backend = get_storage_backend()
metadata_repository = get_metadata_repository()

# Not called eagerly here (unlike storage_backend/metadata_repository
# above) - get_vector_store() always builds a real Postgres/pgvector
# connection (there's no sqlite-style test backend for it the way
# METADATA_BACKEND has), so constructing it at import time would make
# merely importing this module depend on Postgres being up. It's
# called lazily inside the /process endpoint instead, which also lets
# tests monkeypatch this function directly (see tests/conftest.py's
# _fake_vector_store fixture) instead of needing a real database.


app = FastAPI(
    title="Secure RAG Storage - Admin API",
    description=(
        "Upload documents into categorized folders and run them "
        "through extraction, segmentation, chunking, embedding, and "
        "pgvector indexing. POST /search runs hybrid retrieval over "
        "them (Owner/Admin scope); app/api/end_user_api.py's "
        "/end-user/* routes expose Q&A and document comparison to a "
        "separate, more restricted End User scope on top of the same "
        "pipeline."
    ),
    version="0.3.0",
)
app.include_router(auth_router)


# ----------------------------------------------------------------------
# OpenAPI schema patch: add back `format: binary` on the batch upload
# endpoint's `files` array items.
#
# FastAPI 0.141 emits OpenAPI 3.1, where UploadFile's schema is
# {"type": "string", "contentMediaType": "application/octet-stream"}
# (JSON Schema 2020-12's binary-content keyword) instead of OpenAPI
# 3.0's {"type": "string", "format": "binary"}. Swagger UI's
# single-file widget recognizes both keywords and renders a working
# file picker either way, but its array-of-files widget only checks
# for the older `format: binary` - given just contentMediaType, it
# falls back to a generic "Add string item" box. Adding format:
# binary back (alongside, not instead of, contentMediaType, so this
# stays a valid description of the same field) gives Swagger UI's
# array widget the keyword it's actually looking for.
#
# Confirmed fixed in a live browser: /docs now renders a real
# multi-file picker for POST /categories/{category}/documents/batch.
# ----------------------------------------------------------------------

_generate_openapi = app.openapi


def _openapi_with_binary_array_format() -> dict:
    schema = _generate_openapi()

    batch_schema = schema.get("components", {}).get("schemas", {}).get(
        "Body_upload_documents_batch_categories__category__documents_batch_post"
    )

    if batch_schema:
        batch_schema["properties"]["files"]["items"]["format"] = "binary"

    return schema


app.openapi = _openapi_with_binary_array_format


# End User API - a separate scope (X-End-User-Key, not X-API-Key) on
# top of the same pipeline. See app/api/end_user_api.py.
from app.api.end_user_api import router as end_user_router  # noqa: E402

app.include_router(end_user_router)

# Client Intake API - Phase 3 foundation, same X-End-User-Key scope as
# end_user_router. See app/api/intake_api.py.
from app.api.intake_api import router as intake_router  # noqa: E402

app.include_router(intake_router)


@app.get("/")
def root() -> dict:
    return {
        "service": "Secure RAG Storage - Admin API",
        "docs": "/docs",
    }


_UPLOAD_TEST_PAGE = """
<!doctype html>
<title>Batch upload test</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 3rem auto; }
  input, button { font-size: 1rem; padding: 0.4rem; }
  input[type=text] { width: 100%; box-sizing: border-box; margin-bottom: 1rem; }
  pre { background: #f4f4f4; padding: 1rem; overflow-x: auto; white-space: pre-wrap; }
</style>
<h1>Batch upload test</h1>
<p>
  A plain HTML form for manually testing
  <code>POST /categories/{category}/documents/batch</code> - Swagger UI's
  "Try it out" cannot render a real file picker for an array of files
  (see the endpoint's docstring), but a normal
  <code>&lt;input type="file" multiple&gt;</code> always can.
</p>
<label>Admin API key (X-API-Key header)</label>
<input type="text" id="apiKey" placeholder="paste your ADMIN_API_KEY">
<label>Category (may include subfolders, e.g. Contracts/2024)</label>
<input type="text" id="category" value="Demo">
<label>Files</label><br>
<input type="file" id="files" multiple>
<br><br>
<button id="submit">Upload batch</button>
<pre id="result"></pre>
<script>
  document.getElementById("submit").onclick = async () => {
    const apiKey = document.getElementById("apiKey").value.trim();
    const category = document.getElementById("category").value.trim();
    const files = document.getElementById("files").files;
    const result = document.getElementById("result");

    if (!apiKey) {
      result.textContent = "Paste your admin API key (ADMIN_API_KEY in .env).";
      return;
    }

    if (!category || files.length === 0) {
      result.textContent = "Pick a category and at least one file.";
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    result.textContent = "Uploading...";

    try {
      const response = await fetch(
        `/categories/${encodeURIComponent(category)}/documents/batch`,
        { method: "POST", headers: { "X-API-Key": apiKey }, body: formData }
      );
      const body = await response.json();
      result.textContent = JSON.stringify(body, null, 2);
    } catch (err) {
      result.textContent = "Request failed: " + err;
    }
  };
</script>
"""


@app.get("/upload-test", response_class=HTMLResponse)
def upload_test_page() -> str:
    """
    Plain HTML page for manually testing batch upload in a browser.

    Exists solely to work around Swagger UI not rendering a real
    file picker for POST /categories/{category}/documents/batch's
    `files` array field - see that endpoint's docstring for why.
    """

    return _UPLOAD_TEST_PAGE


# ----------------------------------------------------------------------
# Admin Dashboard / End User UI
#
# Static single-page apps served straight off disk (app/static/) -
# no build step, no separate frontend project. Like /upload-test,
# these page routes carry no `require_admin_key`/`require_end_user_key`
# dependency (a plain browser navigation can't attach an Authorization
# or X-End-User-Key header) - the pages themselves are just static
# HTML/JS; every API call their JS makes attaches the real credential
# (JWT bearer token for the dashboard, X-End-User-Key for the End
# User page) and is authenticated exactly like any curl/Swagger call
# to the same endpoint.
# ----------------------------------------------------------------------

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get(
    "/admin/stats",
    dependencies=[Depends(require_admin_key)],
)
def admin_stats() -> dict:
    """Return server-side document and storage statistics for the admin dashboard."""

    documents = metadata_repository.list_documents()
    folders = metadata_repository.list_folders()

    status_counts = {
        "Uploaded": 0,
        "Processing": 0,
        "Indexed": 0,
        "Failed": 0,
    }

    total_size = 0

    for document in documents:
        status = document.get("status", "Uploaded")
        if status in status_counts:
            status_counts[status] += 1

        total_size += int(document.get("size", 0) or 0)

    return {
        "total_documents": len(documents),
        "total_categories": len(folders),
        "storage_bytes": total_size,
        "storage_mb": round(total_size / (1024 * 1024), 2),
        "status_counts": status_counts,
    }


@app.get(
    "/admin/disclaimer",
    response_model=DisclaimerResponse,
    dependencies=[Depends(require_admin_key)],
)
def get_disclaimer() -> DisclaimerResponse:
    """Return the disclaimer currently shown on every DOCX/PDF analysis report export."""

    disclaimer = metadata_repository.get_disclaimer()

    if disclaimer is None:
        return DisclaimerResponse(text=DEFAULT_DISCLAIMER_TEXT)

    return DisclaimerResponse(
        text=disclaimer["text"],
        updated_at=str(disclaimer["updated_at"]),
        updated_by=disclaimer["updated_by"],
    )


@app.put(
    "/admin/disclaimer",
    response_model=DisclaimerResponse,
)
def update_disclaimer(
    request: DisclaimerUpdateRequest,
    owner: dict | None = Depends(require_admin_key),
) -> DisclaimerResponse:
    """
    Update the disclaimer shown on every DOCX/PDF analysis report
    export (app/analysis/report_export.py) - takes effect on the very
    next export, no restart needed.
    """

    updated_by = owner.get("email") if owner else None
    disclaimer = metadata_repository.update_disclaimer(request.text, updated_by=updated_by)

    log_audit_event("update_disclaimer", actor=updated_by or "admin")

    return DisclaimerResponse(
        text=disclaimer["text"],
        updated_at=str(disclaimer["updated_at"]),
        updated_by=disclaimer["updated_by"],
    )


@app.get(
    "/admin/matters",
    response_model=MatterListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_matters() -> MatterListResponse:
    """
    List every Matter (an isolated End User identity - its own
    X-End-User-Key, its own threads at POST /end-user/threads,
    invisible to every other Matter). Never returns API keys, only
    their existence - a key can only ever be seen once, at creation.
    """

    matters = metadata_repository.list_matters()

    return MatterListResponse(
        matters=[
            MatterInfo(
                id=m["id"],
                name=m["name"],
                is_active=bool(m["is_active"]),
                created_at=str(m["created_at"]),
            )
            for m in matters
        ]
    )


@app.post(
    "/admin/matters",
    response_model=MatterCreatedResponse,
)
def create_matter(
    request: MatterCreateRequest,
    owner: dict | None = Depends(require_admin_key),
) -> MatterCreatedResponse:
    """
    Create a new Matter - generates a fresh X-End-User-Key, returned
    here in PLAINTEXT exactly once. Only its SHA-256 hash
    (app/security/auth.py's hash_api_key()) is ever stored, so it
    cannot be retrieved again after this response - give it to
    whoever should authenticate as this Matter now.
    """

    api_key = secrets.token_urlsafe(32)
    matter = metadata_repository.create_matter(request.name, hash_api_key(api_key))

    log_audit_event(
        "create_matter",
        detail=f"matter '{request.name}' created",
        actor=owner.get("email") if owner else "admin",
    )

    return MatterCreatedResponse(
        id=matter["id"],
        name=matter["name"],
        api_key=api_key,
        created_at=str(matter["created_at"]),
    )


@app.get(
    "/admin/retrieval-settings",
    response_model=RetrievalSettingsResponse,
    dependencies=[Depends(require_admin_key)],
)
def get_retrieval_settings() -> RetrievalSettingsResponse:
    """Return the Top K / score threshold / minimum chunks currently used by POST /end-user/query and /end-user/query/stream."""

    settings = metadata_repository.get_retrieval_settings()

    if settings is None:
        return RetrievalSettingsResponse(
            top_k=DEFAULT_TOP_K,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
            min_chunks=DEFAULT_MIN_CHUNKS,
        )

    return RetrievalSettingsResponse(
        top_k=settings["top_k"],
        score_threshold=settings["score_threshold"],
        min_chunks=settings["min_chunks"],
        updated_at=str(settings["updated_at"]),
        updated_by=settings["updated_by"],
    )


@app.put(
    "/admin/retrieval-settings",
    response_model=RetrievalSettingsResponse,
)
def update_retrieval_settings(
    request: RetrievalSettingsUpdateRequest,
    owner: dict | None = Depends(require_admin_key),
) -> RetrievalSettingsResponse:
    """
    Update Top K / score threshold / minimum chunks for the hybrid
    retrieval pipeline - takes effect on the very next
    POST /end-user/query or /end-user/query/stream call.
    """

    updated_by = owner.get("email") if owner else None
    settings = metadata_repository.update_retrieval_settings(
        top_k=request.top_k,
        score_threshold=request.score_threshold,
        min_chunks=request.min_chunks,
        updated_by=updated_by,
    )

    log_audit_event("update_retrieval_settings", actor=updated_by or "admin")

    return RetrievalSettingsResponse(
        top_k=settings["top_k"],
        score_threshold=settings["score_threshold"],
        min_chunks=settings["min_chunks"],
        updated_at=str(settings["updated_at"]),
        updated_by=settings["updated_by"],
    )


@app.get(
    "/admin/prompts/{name}",
    response_model=PromptVersionListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_prompt_versions(name: str) -> PromptVersionListResponse:
    """
    List every saved version of a system prompt, newest first - `name`
    is "narrative_system_prompt" (app/analysis/claude_narrative.py) or
    "answer_system_prompt" (app/analysis/answer_generation.py).
    """

    versions = metadata_repository.list_prompt_versions(name)

    return PromptVersionListResponse(
        name=name,
        versions=[
            PromptVersionInfo(
                name=v["name"],
                version=v["version"],
                text=v["text"],
                is_active=bool(v["is_active"]),
                created_at=str(v["created_at"]),
                created_by=v["created_by"],
            )
            for v in versions
        ],
    )


@app.post(
    "/admin/prompts/{name}",
    response_model=PromptVersionInfo,
)
def create_prompt_version(
    name: str,
    request: PromptVersionCreateRequest,
    owner: dict | None = Depends(require_admin_key),
) -> PromptVersionInfo:
    """Save and activate a new version of a system prompt - the previous version stays in history, rollback-able."""

    updated_by = owner.get("email") if owner else None
    version = metadata_repository.create_prompt_version(name, request.text, created_by=updated_by)

    log_audit_event(
        "create_prompt_version", detail=f"{name} v{version['version']}", actor=updated_by or "admin"
    )

    return PromptVersionInfo(
        name=version["name"],
        version=version["version"],
        text=version["text"],
        is_active=bool(version["is_active"]),
        created_at=str(version["created_at"]),
        created_by=version["created_by"],
    )


@app.post(
    "/admin/prompts/{name}/activate/{version}",
    response_model=PromptVersionInfo,
)
def activate_prompt_version(
    name: str,
    version: int,
    owner: dict | None = Depends(require_admin_key),
) -> PromptVersionInfo:
    """Roll back (or forward) to a previously saved version - makes it active again."""

    try:
        activated = metadata_repository.activate_prompt_version(name, version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    log_audit_event(
        "activate_prompt_version",
        detail=f"{name} -> v{version}",
        actor=owner.get("email") if owner else "admin",
    )

    return PromptVersionInfo(
        name=activated["name"],
        version=activated["version"],
        text=activated["text"],
        is_active=True,
        created_at=str(activated["created_at"]),
        created_by=activated["created_by"],
    )


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard_page() -> str:
    """
    Admin Dashboard: log in as Owner, see folder/document/status counts
    and storage usage, and manage the whole category/document tree
    (create/rename/delete folders, upload/delete files, trigger
    processing) - all on top of the endpoints already defined above.
    """

    return (_STATIC_DIR / "admin_dashboard.html").read_text(encoding="utf-8")


@app.get("/analyze", response_class=HTMLResponse)
def end_user_page() -> str:
    """
    End User interface: paste text or upload a PDF/DOCX/TXT, click
    Analyze, and see the structured comparison report from
    POST /end-user/compare (app/api/end_user_api.py) rendered in the
    browser instead of raw JSON.
    """

    return (_STATIC_DIR / "end_user.html").read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Categories
# ----------------------------------------------------------------------


@app.post(
    "/categories",
    response_model=CategoryInfo,
    dependencies=[Depends(require_admin_key)],
)
def create_category(request: CategoryCreateRequest) -> CategoryInfo:
    """
    Create a category (a folder that uploaded documents get grouped
    into).

    Pass `parent` to create it as a subfolder of an existing
    category, e.g. {"name": "2024", "parent": "Contracts"} creates
    "Contracts/2024".
    """

    full_path = f"{request.parent}/{request.name}" if request.parent else request.name
    safe_category = storage_backend.create_category(full_path)
    metadata_repository.create_folder(safe_category)
    return CategoryInfo(name=safe_category, document_count=0)


@app.get(
    "/categories",
    response_model=CategoryListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_categories() -> CategoryListResponse:
    categories = [CategoryInfo(**c) for c in metadata_repository.list_folders()]
    return CategoryListResponse(categories=categories)


# NOTE: rename_category/delete_category are defined further below,
# after the document endpoints. Route matching tries registered
# routes in order, and both use a greedy {category:path} that would
# otherwise shadow the more specific .../documents/{filename} routes
# for the same HTTP method (PATCH has no conflict, but DELETE does -
# DELETE /categories/{category} must not be registered before DELETE
# /categories/{category}/documents/{filename}).


# ----------------------------------------------------------------------
# Documents
# ----------------------------------------------------------------------


def _store_upload(upload_bytes: bytes, filename: str, category: str) -> UploadedFileResult:

    is_valid, reason = validate_file_object(filename, len(upload_bytes))

    if not is_valid:
        result = storage_backend.quarantine(category, filename, io.BytesIO(upload_bytes))
        log_audit_event(
            "upload",
            category=result["category"],
            filename=result["stored_filename"],
            status="rejected",
            detail=reason,
        )
        return UploadedFileResult(
            filename=result["stored_filename"],
            category=result["category"],
            status="rejected",
            reason=reason,
        )

    result = storage_backend.save(category, filename, io.BytesIO(upload_bytes))

    metadata_repository.upsert_document(
        category=result["category"],
        filename=result["stored_filename"],
        extension=Path(result["stored_filename"]).suffix.lower(),
        size=result["size"],
        sha256=result["sha256"],
        status=DocumentStatus.UPLOADED.value,
    )

    log_audit_event(
        "upload",
        category=result["category"],
        filename=result["stored_filename"],
        status="success",
    )

    return UploadedFileResult(
        filename=result["stored_filename"],
        category=result["category"],
        status="stored",
        reason="valid",
        size=result["size"],
        sha256=result["sha256"],
    )


@app.post(
    "/categories/{category:path}/documents",
    response_model=UploadResponse,
    dependencies=[Depends(require_admin_key)],
)
async def upload_document(
    category: str,
    file: UploadFile = File(...),
) -> UploadResponse:
    """
    Upload one PDF/DOCX/TXT file into a category.

    The file is validated the same way the CLI ingestion path
    validates files (extension, non-empty, size limit). A file that
    fails validation is moved to quarantine instead of protected
    storage, and reported back with the rejection reason.
    """

    safe_category = storage_backend.create_category(category)
    metadata_repository.create_folder(safe_category)
    data = await file.read()
    result = _store_upload(data, file.filename or "unnamed", category)
    await file.close()

    return UploadResponse(
        category=result.category,
        results=[result],
        total_uploaded=1,
        total_stored=1 if result.status == "stored" else 0,
        total_rejected=1 if result.status == "rejected" else 0,
    )


@app.post(
    "/categories/{category:path}/documents/batch",
    response_model=UploadResponse,
    dependencies=[Depends(require_admin_key)],
)
async def upload_documents_batch(
    category: str,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """
    Upload several PDF/DOCX/TXT files in one request.

    Swagger UI's array-of-files widget needs the classic OpenAPI 3.0
    `format: binary` keyword to render a real file picker per item -
    FastAPI's default OpenAPI 3.1 output doesn't include it (it uses
    `contentMediaType` instead), so the openapi() patch above adds it
    back into the generated schema for this endpoint specifically.
    /docs renders a working multi-file picker as a result.

    GET /upload-test remains available as a plain-HTML alternative.
    """

    safe_category = storage_backend.create_category(category)
    metadata_repository.create_folder(safe_category)

    results = []
    for upload in files:
        data = await upload.read()
        results.append(_store_upload(data, upload.filename or "unnamed", category))
        await upload.close()

    total_stored = sum(1 for r in results if r.status == "stored")
    total_rejected = sum(1 for r in results if r.status == "rejected")

    safe_category = results[0].category if results else category

    return UploadResponse(
        category=safe_category,
        results=results,
        total_uploaded=len(results),
        total_stored=total_stored,
        total_rejected=total_rejected,
    )


@app.put(
    "/categories/{category:path}/documents/{filename}",
    response_model=UploadedFileResult,
    dependencies=[Depends(require_admin_key)],
)
async def replace_document(
    category: str,
    filename: str,
    file: UploadFile = File(...),
) -> UploadedFileResult:
    """Replace/update an existing file's contents, keeping its name."""

    data = await file.read()
    await file.close()

    is_valid, reason = validate_file_object(filename, len(data))
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid replacement file: {reason}")

    try:
        result = storage_backend.replace(category, filename, io.BytesIO(data))
    except FileNotFoundError as exc:
        log_audit_event(
            "replace", category=category, filename=filename, status="not_found"
        )
        raise HTTPException(status_code=404, detail=str(exc))

    metadata_repository.upsert_document(
        category=result["category"],
        filename=result["stored_filename"],
        extension=Path(result["stored_filename"]).suffix.lower(),
        size=result["size"],
        sha256=result["sha256"],
        status=DocumentStatus.UPLOADED.value,
    )

    log_audit_event(
        "replace", category=result["category"], filename=result["stored_filename"]
    )

    return UploadedFileResult(
        filename=result["stored_filename"],
        category=result["category"],
        status="stored",
        reason="valid",
        size=result["size"],
        sha256=result["sha256"],
    )


@app.delete(
    "/categories/{category:path}/documents/{filename}",
    response_model=MessageResponse,
    dependencies=[Depends(require_admin_key)],
)
def delete_document(category: str, filename: str) -> MessageResponse:
    """Delete one file from protected storage."""

    deleted = storage_backend.delete(category, filename)

    if not deleted:
        log_audit_event(
            "delete_document", category=category, filename=filename, status="not_found"
        )
        raise HTTPException(status_code=404, detail=f"File not found: {category}/{filename}")

    safe_category = sanitize_category_path(category)
    safe_filename = sanitize_path_segment(Path(filename).name)
    metadata_repository.delete_document(safe_category, safe_filename)

    log_audit_event("delete_document", category=safe_category, filename=safe_filename)

    return MessageResponse(message=f"'{filename}' deleted from '{category}'.")


@app.get(
    "/documents",
    response_model=DocumentListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_documents(category: str | None = None) -> DocumentListResponse:
    documents = [
        DocumentInfo(
            filename=d["filename"],
            category=d["category"],
            relative_path=d["relative_path"],
            extension=d["extension"],
            size=d["size"],
            status=d["status"],
        )
        for d in metadata_repository.list_documents(category)
    ]
    return DocumentListResponse(documents=documents, total=len(documents))


# ----------------------------------------------------------------------
# Categories - rename/delete
#
# Registered after the document endpoints on purpose (see the note
# above the Documents section): both use a greedy {category:path}
# matcher, and DELETE must not shadow DELETE .../documents/{filename}.
# ----------------------------------------------------------------------


@app.patch(
    "/categories/{category:path}",
    response_model=CategoryInfo,
    dependencies=[Depends(require_admin_key)],
)
def rename_category(category: str, request: CategoryRenameRequest) -> CategoryInfo:
    """Rename/move a category (and everything stored under it)."""

    safe_old = sanitize_category_path(category)

    try:
        new_name = storage_backend.rename_category(category, request.new_name)
    except FileNotFoundError as exc:
        log_audit_event("rename_category", category=safe_old, status="not_found")
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        log_audit_event(
            "rename_category", category=safe_old, status="conflict", detail=str(exc)
        )
        raise HTTPException(status_code=409, detail=str(exc))

    metadata_repository.rename_folder(safe_old, new_name)

    log_audit_event(
        "rename_category", category=safe_old, detail=f"renamed to '{new_name}'"
    )

    updated = next(
        (c for c in metadata_repository.list_folders() if c["name"] == new_name),
        {"name": new_name, "document_count": 0},
    )
    return CategoryInfo(**updated)


@app.delete(
    "/categories/{category:path}",
    response_model=MessageResponse,
    dependencies=[Depends(require_admin_key)],
)
def delete_category(category: str, force: bool = False) -> MessageResponse:
    """
    Delete a category.

    By default this refuses to delete a category that still has
    files in it - pass ?force=true to delete it and everything
    inside it anyway.
    """

    safe_category = sanitize_category_path(category)

    try:
        deleted = storage_backend.delete_category(category, force=force)
    except ValueError as exc:
        log_audit_event(
            "delete_category", category=safe_category, status="conflict", detail=str(exc)
        )
        raise HTTPException(status_code=409, detail=str(exc))

    if not deleted:
        log_audit_event("delete_category", category=safe_category, status="not_found")
        raise HTTPException(status_code=404, detail=f"Category not found: {category}")

    metadata_repository.delete_folder(safe_category)

    log_audit_event(
        "delete_category", category=safe_category, detail=f"force={force}"
    )

    return MessageResponse(message=f"Category '{category}' deleted.")


# ----------------------------------------------------------------------
# Processing
#
# The actual extraction -> segmentation -> chunking -> embeddings
# pipeline (app/jobs/processing.py:run_processing_job) runs in a
# separate RQ worker process (scripts/worker.py), picking jobs off a
# Redis-backed queue (app/jobs/queue.py). POST /process only enqueues
# the job and returns - it never blocks waiting for processing to
# finish, so uploads and status polls stay responsive while a large
# document is (slowly) being processed in the background. Poll
# GET /process/{job_id} for the job's own status, or GET /documents
# for live per-document status (Uploaded -> Processing -> Embedding ->
# Indexed / Failed).
# ----------------------------------------------------------------------


@app.post(
    "/process",
    response_model=ProcessQueuedResponse,
    dependencies=[Depends(require_admin_key)],
)
def process_documents() -> ProcessQueuedResponse:
    """
    Enqueue a background job that runs every stored document through
    extraction, segmentation, chunking and embedding generation.
    Returns immediately with a `queued` status instead of waiting for
    processing to finish - safe to call again after new uploads, it
    always reprocesses everything currently in storage.

    Poll GET /process/{job_id} with the returned `job_id` for the
    job's status/result, or GET /documents for per-document status.
    """

    job = get_job_queue().enqueue(run_processing_job, metadata_repository, get_vector_store())

    return ProcessQueuedResponse(job_id=job.id, status="queued")


@app.get(
    "/process/{job_id}",
    response_model=ProcessStatusResponse,
    dependencies=[Depends(require_admin_key)],
)
def process_status(job_id: str) -> ProcessStatusResponse:
    """Poll a background processing job started by POST /process."""

    job = get_job_queue().fetch_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"No processing job found: {job_id}")

    status = job.get_status(refresh=True)

    return ProcessStatusResponse(
        job_id=job.id,
        status=status,
        result=ProcessResult(**job.result) if status == "finished" else None,
        error=str(job.exc_info) if status == "failed" else None,
    )


# ----------------------------------------------------------------------
# Retrieval
#
# The hybrid pipeline itself (query embedding -> vector search +
# keyword search + metadata filtering -> reranking -> top chunks)
# lives in app/retrieval/ - this endpoint is a thin wrapper so it can
# be exercised the same way every other feature in this API is: a
# request with the admin key, no separate client needed.
# ----------------------------------------------------------------------


@app.post(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(require_admin_key)],
)
def search_chunks(request: SearchRequest) -> SearchResponse:
    """
    Run the hybrid retrieval pipeline (app/retrieval/retriever.py) for
    `query` and return its top `top_k` chunks, most relevant first.

    Only searches chunks that have made it to pgvector - i.e. from
    documents already `Indexed` (see GET /documents). Pass `category`
    to restrict the search to one category (including its subfolders).
    """

    results = retrieve(request.query, top_k=request.top_k, category=request.category)

    return SearchResponse(
        query=request.query,
        results=[SearchResultChunk(**result) for result in results],
    )

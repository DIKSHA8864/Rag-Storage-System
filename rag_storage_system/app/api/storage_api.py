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
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
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
    OwnerResearchExportRequest,
    OwnerResearchRequest,
    OwnerResearchResponse,
    OwnerResearchSource,
    UploadedFileResult,
    UploadResponse,
    PendingReportInfo,
    ReportReviewListResponse,
    ReportRejectRequest,
    ReportReviewInfo,
    MatterAssignmentCreateRequest,
    MatterAssignmentInfo,
    MatterAssignmentListResponse,
    MatterIntakeSessionDetailResponse,
    IntakeSessionInfo,
    IntakeSessionListResponse,
    TimelineEventInfo,
    UploadedInputInfo,
    InterviewFactInfo,
    ReportInfo,
    MatterResearchSuggestion,
    MatterResearchSuggestionCitation,
    MatterResearchSuggestionsResponse,
)
from app.security.auth import ensure_matter_access
from app.disclaimer import DEFAULT_DISCLAIMER_TEXT, get_current_disclaimer_text
from app.ingestion.file_validator import validate_file_object
from app.jobs.processing import run_processing_job
from app.jobs.queue import get_job_queue
from app.metadata import get_metadata_repository
from app.metadata.models import DocumentStatus
from app.retrieval.retriever import retrieve, retrieve_for_matter
from app.retrieval_settings import DEFAULT_MIN_CHUNKS, DEFAULT_SCORE_THRESHOLD, DEFAULT_TOP_K, get_current_retrieval_settings
from app.analysis.answer_generation import stream_grounded_answer
from app.billing import get_billing_service
from app.billing.service import RESOURCE_DOCUMENTS, RESOURCE_LLM_CALLS, RESOURCE_MATTERS, RESOURCE_STORAGE_BYTES, PlanLimitExceededError
from app.report.rag_analysis import gather_fact_support
from app.analysis.report_export import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    build_owner_research_docx,
    build_owner_research_pdf,
)
from app.security.audit_log import log_audit_event
from app.security.auth import hash_api_key, require_admin_key
from app.security.path_security import sanitize_category_path, sanitize_path_segment
from app.storage import get_storage_backend
from app.vector_store import get_vector_store
from config.settings import get_settings

logger = logging.getLogger(__name__)

storage_backend = get_storage_backend()
metadata_repository = get_metadata_repository()


def _enforce_plan_limit(tenant_id: int, resource: str, requested_increment: int = 1) -> None:
    """
    Raise HTTP 402 Payment Required if consuming `requested_increment`
    more of `resource` would exceed `tenant_id`'s plan limit - see
    app/billing/service.py's check_limit() for exactly when this does
    (and, more often, deliberately does not) block. References the
    bare `metadata_repository` name so a test's
    monkeypatch.setattr(storage_api, "metadata_repository", ...) is
    always respected, same as every other endpoint in this module.
    """

    try:
        get_billing_service(metadata_repository).check_limit(tenant_id, resource, requested_increment)
    except PlanLimitExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc))

# Not called eagerly here (unlike storage_backend/metadata_repository
# above) - get_vector_store() always builds a real Postgres/pgvector
# connection (there's no sqlite-style test backend for it the way
# METADATA_BACKEND has), so constructing it at import time would make
# merely importing this module depend on Postgres being up. It's
# called lazily inside the /process endpoint instead, which also lets
# tests monkeypatch this function directly (see tests/conftest.py's
# _fake_vector_store fixture) instead of needing a real database.


_settings = get_settings()
if _settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=_settings.sentry_dsn, environment=_settings.environment, traces_sample_rate=0.1)

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

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.security.rate_limit import limiter

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=False,  # JWT goes in the Authorization header, not a cookie - no credentials needed
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again shortly."})


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

# Guided Intake Engine - same X-End-User-Key scope as intake_router. See app/api/interview_api.py.
from app.api.interview_api import router as interview_router  # noqa: E402

app.include_router(interview_router)

# Complaint Generator - Owner-JWT scoped (not X-End-User-Key). See app/api/complaint_api.py.
from app.api.complaint_api import router as complaint_router  # noqa: E402

app.include_router(complaint_router)

# Billing / Subscription (Phase 5 Step 25) - Owner-JWT scoped. See app/api/billing_api.py.
from app.api.billing_api import router as billing_router  # noqa: E402

app.include_router(billing_router)

# End-user accounts: Owner-only user management + public signup/login.
# See app/api/users_api.py, app/api/end_user_auth_api.py.
from app.api.users_api import router as users_router  # noqa: E402
from app.api.end_user_auth_api import router as end_user_auth_router  # noqa: E402

app.include_router(users_router)
app.include_router(end_user_auth_router)


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
        "Embedding": 0,
        "Indexed": 0,
        "Failed": 0,
    }

    total_size = 0
    last_synced_at = None

    for document in documents:
        status = document.get("status", "Uploaded")
        if status in status_counts:
            status_counts[status] += 1

        total_size += int(document.get("size", 0) or 0)

        # "Last sync" = the most recent time any document's status row
        # actually changed (upload, processing, indexing, or failure) -
        # documents.updated_at already tracks this for every status
        # transition (see update_document_status()/update_status_where()
        # in app/metadata/), so this is a real, already-recorded
        # timestamp, not a new sync-log system.
        updated_at = document.get("updated_at")
        if updated_at and (last_synced_at is None or str(updated_at) > last_synced_at):
            last_synced_at = str(updated_at)

    return {
        "total_documents": len(documents),
        "total_categories": len(folders),
        "storage_bytes": total_size,
        "storage_mb": round(total_size / (1024 * 1024), 2),
        "status_counts": status_counts,
        "last_synced_at": last_synced_at,
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
def list_matters(owner: dict = Depends(require_admin_key)) -> MatterListResponse:
    """
    List every Matter belonging to the caller's own tenant (an
    isolated End User identity - its own X-End-User-Key, its own
    threads at POST /end-user/threads, invisible to every other
    Matter, AND invisible to every other tenant). Never returns API
    keys, only their existence - a key can only ever be seen once, at
    creation.
    """

    matters = metadata_repository.list_matters(tenant_id=owner["tenant_id"])

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
    tenant_id = owner["tenant_id"] if owner else 1
    _enforce_plan_limit(tenant_id, RESOURCE_MATTERS)
    matter = metadata_repository.create_matter(request.name, hash_api_key(api_key), tenant_id=tenant_id)

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

@app.post(
    "/admin/matters/{matter_id}/assignments",
    response_model=MatterAssignmentInfo,
    dependencies=[Depends(require_admin_key)],
)
def assign_matter(matter_id: int, request: MatterAssignmentCreateRequest, owner: dict = Depends(require_admin_key)) -> MatterAssignmentInfo:
    """
    Assign a firm staff account (attorney/paralegal) to a Matter -
    only 'owner'-role accounts may do this (an attorney cannot grant
    themselves or anyone else access to a Matter they don't already
    have).
    """

    if owner.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only an Owner-role account may assign Matters.")

    if request.role not in ("attorney", "paralegal"):
        raise HTTPException(status_code=400, detail="`role` must be 'attorney' or 'paralegal'.")

    # Tenant isolation + existence check (404s exactly the same way for
    # "no such Matter" and "that Matter belongs to a different tenant" -
    # an Owner must never be able to grant, or even probe for, access to
    # another firm's Matter).
    ensure_matter_access(owner, matter_id, metadata_repository)

    assignment = metadata_repository.create_matter_assignment(request.owner_id, matter_id, request.role)
    return MatterAssignmentInfo(
        id=assignment["id"], owner_id=assignment["owner_id"], matter_id=assignment["matter_id"],
        role=assignment["role"], assigned_at=str(assignment["assigned_at"]),
    )


@app.get(
    "/admin/matters/{matter_id}/assignments",
    response_model=MatterAssignmentListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_matter_assignments(matter_id: int, owner: dict = Depends(require_admin_key)) -> MatterAssignmentListResponse:
    ensure_matter_access(owner, matter_id, metadata_repository)
    assignments = metadata_repository.list_assignments_for_matter(matter_id)
    return MatterAssignmentListResponse(
        assignments=[
            MatterAssignmentInfo(
                id=a["id"], owner_id=a["owner_id"], matter_id=a["matter_id"],
                role=a["role"], assigned_at=str(a["assigned_at"]),
            )
            for a in assignments
        ]
    )


@app.get(
    "/admin/matters/{matter_id}",
    response_model=MatterInfo,
    dependencies=[Depends(require_admin_key)],
)
def get_matter_detail(matter_id: int, owner: dict = Depends(require_admin_key)) -> MatterInfo:
    """Real, single-Matter detail - same isolation as every other Matter-scoped endpoint."""

    ensure_matter_access(owner, matter_id, metadata_repository)

    matter = metadata_repository.get_matter(matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")

    return MatterInfo(
        id=matter["id"], name=matter["name"], is_active=bool(matter["is_active"]), created_at=str(matter["created_at"]),
    )


@app.get(
    "/admin/matters/{matter_id}/intake-sessions",
    response_model=IntakeSessionListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_matter_intake_sessions(matter_id: int, owner: dict = Depends(require_admin_key)) -> IntakeSessionListResponse:
    """
    Every intake session a Client has started under this Matter - the
    Owner-side view of exactly what GET /end-user/intake/sessions
    already returns to the Client themselves, scoped the same way.
    """

    ensure_matter_access(owner, matter_id, metadata_repository)

    sessions = metadata_repository.list_intake_sessions(matter_id)
    return IntakeSessionListResponse(
        sessions=[
            IntakeSessionInfo(
                id=s["id"], matter_id=s["matter_id"], thread_id=s.get("thread_id"),
                title=s["title"], status=s["status"],
                created_at=str(s["created_at"]), updated_at=str(s["updated_at"]),
            )
            for s in sessions
        ]
    )


@app.get(
    "/admin/matters/{matter_id}/intake-sessions/{session_id}",
    response_model=MatterIntakeSessionDetailResponse,
    dependencies=[Depends(require_admin_key)],
)
def get_matter_intake_session_detail(
    matter_id: int, session_id: int, owner: dict = Depends(require_admin_key)
) -> MatterIntakeSessionDetailResponse:
    """
    One intake session's full real record for the Owner: the session
    itself, its timeline, every uploaded document, every recorded
    fact, and any generated reports - the same rows the Client's own
    session view is built from, never a second copy of them.
    """

    ensure_matter_access(owner, matter_id, metadata_repository)

    session = metadata_repository.get_intake_session(session_id, matter_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Intake session not found.")

    timeline = metadata_repository.list_timeline_events(session_id)
    uploaded_inputs = metadata_repository.list_uploaded_inputs(session_id)
    facts = metadata_repository.list_intake_facts(session_id)
    reports = metadata_repository.list_reports(session_id)

    return MatterIntakeSessionDetailResponse(
        session=IntakeSessionInfo(
            id=session["id"], matter_id=session["matter_id"], thread_id=session.get("thread_id"),
            title=session["title"], status=session["status"],
            created_at=str(session["created_at"]), updated_at=str(session["updated_at"]),
        ),
        timeline=[
            TimelineEventInfo(id=e["id"], event_type=e["event_type"], description=e["description"], created_at=str(e["created_at"]))
            for e in timeline
        ],
        uploaded_inputs=[
            UploadedInputInfo(
                id=u["id"], intake_session_id=u["intake_session_id"], original_filename=u["original_filename"],
                media_type=u["media_type"], size=u["size"], processing_status=u["processing_status"],
                status_detail=u.get("status_detail"), created_at=str(u["created_at"]),
            )
            for u in uploaded_inputs
        ],
        facts=[
            InterviewFactInfo(id=f["id"], category=f["category"], fact_key=f["fact_key"], fact_value=f["fact_value"], created_at=str(f["created_at"]))
            for f in facts
        ],
        reports=[
            ReportInfo(id=r["id"], intake_session_id=r["intake_session_id"], format=r["format"], created_at=str(r["created_at"]))
            for r in reports
        ],
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
)
def list_prompt_versions(name: str, owner: dict = Depends(require_admin_key)) -> PromptVersionListResponse:
    """
    List every saved version of a system prompt, newest first - `name`
    is "narrative_system_prompt" (app/analysis/claude_narrative.py) or
    "answer_system_prompt" (app/analysis/answer_generation.py).
    """

    versions = metadata_repository.list_prompt_versions(name, tenant_id=owner["tenant_id"])

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
    tenant_id = owner["tenant_id"] if owner else 1
    version = metadata_repository.create_prompt_version(name, request.text, created_by=updated_by, tenant_id=tenant_id)

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
        tenant_id = owner["tenant_id"] if owner else 1
        activated = metadata_repository.activate_prompt_version(name, version, tenant_id=tenant_id)
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

@app.get(
    "/admin/reports/pending",
    response_model=ReportReviewListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_pending_reports(owner: dict = Depends(require_admin_key)) -> ReportReviewListResponse:
    """
    List every Client intake report awaiting Owner/attorney review -
    filtered to Matters `owner` may actually access (role=='owner'
    sees everything; an attorney/paralegal sees only assigned Matters).
    """

    reviews = metadata_repository.list_report_reviews(status="pending_review")

    pending = []
    for review in reviews:
        report = metadata_repository.get_report(review["report_id"])
        if report is None:
            continue
        if owner.get("role") != "owner":
            if metadata_repository.get_matter_assignment(int(owner["sub"]), report["matter_id"]) is None:
                continue
        pending.append(
            PendingReportInfo(
                report_id=report["id"],
                intake_session_id=report["intake_session_id"],
                format=report["format"],
                created_at=str(report["created_at"]),
                status=review["status"],
            )
        )

    return ReportReviewListResponse(reports=pending)


@app.post(
    "/admin/reports/{report_id}/approve",
    response_model=ReportReviewInfo,
)
def approve_report(
    report_id: int,
    owner: dict | None = Depends(require_admin_key),
) -> ReportReviewInfo:
    """Approve a Client intake report for release - it becomes downloadable by the End User immediately after."""

    review = metadata_repository.get_report_review(report_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"No review found for report {report_id}.")

    report = metadata_repository.get_report(report_id)
    if report is not None and owner is not None:
        ensure_matter_access(owner, report["matter_id"], metadata_repository)

    updated = metadata_repository.update_report_review(
        report_id, status="approved", reviewed_by=owner.get("email") if owner else "admin"
    )

    log_audit_event("approve_report", detail=f"report {report_id}", actor=owner.get("email") if owner else "admin")

    return ReportReviewInfo(
        report_id=report_id, status=updated["status"], reviewed_by=updated["reviewed_by"],
        reviewed_at=str(updated["reviewed_at"]) if updated["reviewed_at"] else None,
        rejection_reason=updated["rejection_reason"],
    )


@app.post(
    "/admin/reports/{report_id}/reject",
    response_model=ReportReviewInfo,
)
def reject_report(
    report_id: int,
    request: ReportRejectRequest,
    owner: dict | None = Depends(require_admin_key),
) -> ReportReviewInfo:
    """Reject a Client intake report - it stays undownloadable by the End User until a new one is generated and approved."""

    review = metadata_repository.get_report_review(report_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"No review found for report {report_id}.")

    updated = metadata_repository.update_report_review(
        report_id, status="rejected", reviewed_by=owner.get("email") if owner else "admin",
        rejection_reason=request.reason,
    )

    log_audit_event(
        "reject_report", detail=f"report {report_id}: {request.reason}", actor=owner.get("email") if owner else "admin"
    )

    return ReportReviewInfo(
        report_id=report_id, status=updated["status"], reviewed_by=updated["reviewed_by"],
        reviewed_at=str(updated["reviewed_at"]) if updated["reviewed_at"] else None,
        rejection_reason=updated["rejection_reason"],
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
def create_category(request: CategoryCreateRequest, owner: dict = Depends(require_admin_key)) -> CategoryInfo:
    """
    Create a category (a folder that uploaded documents get grouped
    into), owned by the caller's tenant.

    Pass `parent` to create it as a subfolder of an existing
    category, e.g. {"name": "2024", "parent": "Contracts"} creates
    "Contracts/2024".
    """

    full_path = f"{request.parent}/{request.name}" if request.parent else request.name
    stored_category = storage_backend.create_category(_tenant_storage_category(full_path, owner["tenant_id"]))
    safe_category = _strip_tenant_prefix(stored_category, owner["tenant_id"])
    metadata_repository.create_folder(safe_category, tenant_id=owner["tenant_id"])
    return CategoryInfo(name=safe_category, document_count=0)


@app.get(
    "/categories",
    response_model=CategoryListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_categories(owner: dict = Depends(require_admin_key)) -> CategoryListResponse:
    categories = [CategoryInfo(**c) for c in metadata_repository.list_folders(tenant_id=owner["tenant_id"])]
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


def _tenant_storage_category(category: str, tenant_id: int) -> str:
    """
    Physically partitions on-disk storage per tenant, WITHOUT touching
    StorageBackend itself (app/storage/base.py's category-as-folder-path
    abstraction already supports this - same convention
    app/matter_rag/ingestion.py's matter_namespace() already uses for
    per-Matter vector namespaces). Every storage_backend.* call gets
    this tenant-prefixed path; metadata_repository.* calls always keep
    the original, human-readable `category` - see _strip_tenant_prefix().
    """

    prefix = f"tenant-{tenant_id}"
    return f"{prefix}/{category}" if category else prefix


def _strip_tenant_prefix(storage_category: str, tenant_id: int) -> str:
    """Inverse of _tenant_storage_category() - recovers the clean category from what storage_backend returns."""

    prefix = f"tenant-{tenant_id}"
    if storage_category == prefix:
        return ""
    if storage_category.startswith(prefix + "/"):
        return storage_category[len(prefix) + 1:]
    return storage_category


def _store_upload(upload_bytes: bytes, filename: str, category: str, tenant_id: int = 1) -> UploadedFileResult:

    tenant_category = _tenant_storage_category(category, tenant_id)
    is_valid, reason = validate_file_object(filename, len(upload_bytes))

    if not is_valid:
        result = storage_backend.quarantine(tenant_category, filename, io.BytesIO(upload_bytes))
        clean_category = _strip_tenant_prefix(result["category"], tenant_id)
        log_audit_event(
            "upload",
            category=clean_category,
            filename=result["stored_filename"],
            status="rejected",
            detail=reason,
        )
        return UploadedFileResult(
            filename=result["stored_filename"],
            category=clean_category,
            status="rejected",
            reason=reason,
        )

    result = storage_backend.save(tenant_category, filename, io.BytesIO(upload_bytes))
    clean_category = _strip_tenant_prefix(result["category"], tenant_id)

    metadata_repository.upsert_document(
        category=clean_category,
        filename=result["stored_filename"],
        extension=Path(result["stored_filename"]).suffix.lower(),
        size=result["size"],
        sha256=result["sha256"],
        status=DocumentStatus.UPLOADED.value,
        tenant_id=tenant_id,
    )

    log_audit_event(
        "upload",
        category=clean_category,
        filename=result["stored_filename"],
        status="success",
    )

    return UploadedFileResult(
        filename=result["stored_filename"],
        category=clean_category,
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
    owner: dict = Depends(require_admin_key),
) -> UploadResponse:
    """
    Upload one PDF/DOCX/TXT file into a category, owned by the
    caller's tenant.

    The file is validated the same way the CLI ingestion path
    validates files (extension, non-empty, size limit). A file that
    fails validation is moved to quarantine instead of protected
    storage, and reported back with the rejection reason.
    """

    data = await file.read()
    _enforce_plan_limit(owner["tenant_id"], RESOURCE_DOCUMENTS)
    _enforce_plan_limit(owner["tenant_id"], RESOURCE_STORAGE_BYTES, requested_increment=len(data))

    stored_category = storage_backend.create_category(_tenant_storage_category(category, owner["tenant_id"]))
    safe_category = _strip_tenant_prefix(stored_category, owner["tenant_id"])
    metadata_repository.create_folder(safe_category, tenant_id=owner["tenant_id"])
    result = _store_upload(data, file.filename or "unnamed", category, tenant_id=owner["tenant_id"])
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
    owner: dict = Depends(require_admin_key),
) -> UploadResponse:
    """
    Upload several PDF/DOCX/TXT files in one request, owned by the
    caller's tenant.

    Swagger UI's array-of-files widget needs the classic OpenAPI 3.0
    `format: binary` keyword to render a real file picker per item -
    FastAPI's default OpenAPI 3.1 output doesn't include it (it uses
    `contentMediaType` instead), so the openapi() patch above adds it
    back into the generated schema for this endpoint specifically.
    /docs renders a working multi-file picker as a result.

    GET /upload-test remains available as a plain-HTML alternative.
    """

    uploads = []
    for upload in files:
        uploads.append((upload.filename or "unnamed", await upload.read()))
        await upload.close()

    _enforce_plan_limit(owner["tenant_id"], RESOURCE_DOCUMENTS, requested_increment=len(uploads))
    _enforce_plan_limit(
        owner["tenant_id"], RESOURCE_STORAGE_BYTES, requested_increment=sum(len(data) for _, data in uploads)
    )

    stored_category = storage_backend.create_category(_tenant_storage_category(category, owner["tenant_id"]))
    safe_category = _strip_tenant_prefix(stored_category, owner["tenant_id"])
    metadata_repository.create_folder(safe_category, tenant_id=owner["tenant_id"])

    results = []
    for filename, data in uploads:
        results.append(_store_upload(data, filename, category, tenant_id=owner["tenant_id"]))

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
    owner: dict = Depends(require_admin_key),
) -> UploadedFileResult:
    """Replace/update an existing file's contents, keeping its name - only if it belongs to the caller's tenant."""

    safe_category = sanitize_category_path(category)
    safe_filename = sanitize_path_segment(Path(filename).name)
    if metadata_repository.get_document(safe_category, safe_filename, tenant_id=owner["tenant_id"]) is None:
        raise HTTPException(status_code=404, detail=f"File not found: {category}/{filename}")

    data = await file.read()
    await file.close()

    is_valid, reason = validate_file_object(filename, len(data))
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid replacement file: {reason}")

    try:
        result = storage_backend.replace(
            _tenant_storage_category(category, owner["tenant_id"]), filename, io.BytesIO(data)
        )
    except FileNotFoundError as exc:
        log_audit_event(
            "replace", category=category, filename=filename, status="not_found"
        )
        raise HTTPException(status_code=404, detail=str(exc))

    clean_category = _strip_tenant_prefix(result["category"], owner["tenant_id"])

    metadata_repository.upsert_document(
        category=clean_category,
        filename=result["stored_filename"],
        extension=Path(result["stored_filename"]).suffix.lower(),
        size=result["size"],
        sha256=result["sha256"],
        status=DocumentStatus.UPLOADED.value,
        tenant_id=owner["tenant_id"],
    )

    log_audit_event(
        "replace", category=clean_category, filename=result["stored_filename"]
    )

    return UploadedFileResult(
        filename=result["stored_filename"],
        category=clean_category,
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
def delete_document(category: str, filename: str, owner: dict = Depends(require_admin_key)) -> MessageResponse:
    """Delete one file from protected storage - only if it belongs to the caller's tenant."""

    safe_category = sanitize_category_path(category)
    safe_filename = sanitize_path_segment(Path(filename).name)
    if metadata_repository.get_document(safe_category, safe_filename, tenant_id=owner["tenant_id"]) is None:
        log_audit_event(
            "delete_document", category=category, filename=filename, status="not_found"
        )
        raise HTTPException(status_code=404, detail=f"File not found: {category}/{filename}")

    deleted = storage_backend.delete(_tenant_storage_category(category, owner["tenant_id"]), filename)

    if not deleted:
        log_audit_event(
            "delete_document", category=category, filename=filename, status="not_found"
        )
        raise HTTPException(status_code=404, detail=f"File not found: {category}/{filename}")

    metadata_repository.delete_document(safe_category, safe_filename, tenant_id=owner["tenant_id"])

    log_audit_event("delete_document", category=safe_category, filename=safe_filename)

    return MessageResponse(message=f"'{filename}' deleted from '{category}'.")


@app.get(
    "/documents",
    response_model=DocumentListResponse,
    dependencies=[Depends(require_admin_key)],
)
def list_documents(category: str | None = None, owner: dict = Depends(require_admin_key)) -> DocumentListResponse:
    documents = [
        DocumentInfo(
            filename=d["filename"],
            category=d["category"],
            relative_path=d["relative_path"],
            extension=d["extension"],
            size=d["size"],
            status=d["status"],
            status_detail=d.get("status_detail"),
            created_at=str(d["created_at"]),
        )
        for d in metadata_repository.list_documents(category, tenant_id=owner["tenant_id"])
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
def rename_category(
    category: str, request: CategoryRenameRequest, owner: dict = Depends(require_admin_key)
) -> CategoryInfo:
    """Rename/move a category (and everything stored under it) within the caller's tenant."""

    safe_old = sanitize_category_path(category)

    try:
        stored_new_name = storage_backend.rename_category(
            _tenant_storage_category(category, owner["tenant_id"]),
            _tenant_storage_category(request.new_name, owner["tenant_id"]),
        )
    except FileNotFoundError as exc:
        log_audit_event("rename_category", category=safe_old, status="not_found")
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        log_audit_event(
            "rename_category", category=safe_old, status="conflict", detail=str(exc)
        )
        raise HTTPException(status_code=409, detail=str(exc))

    new_name = _strip_tenant_prefix(stored_new_name, owner["tenant_id"])
    metadata_repository.rename_folder(safe_old, new_name, tenant_id=owner["tenant_id"])

    log_audit_event(
        "rename_category", category=safe_old, detail=f"renamed to '{new_name}'"
    )

    updated = next(
        (c for c in metadata_repository.list_folders(tenant_id=owner["tenant_id"]) if c["name"] == new_name),
        {"name": new_name, "document_count": 0},
    )
    return CategoryInfo(**updated)


@app.delete(
    "/categories/{category:path}",
    response_model=MessageResponse,
    dependencies=[Depends(require_admin_key)],
)
def delete_category(category: str, force: bool = False, owner: dict = Depends(require_admin_key)) -> MessageResponse:
    """
    Delete a category within the caller's tenant.

    By default this refuses to delete a category that still has
    files in it - pass ?force=true to delete it and everything
    inside it anyway.
    """

    safe_category = sanitize_category_path(category)

    try:
        deleted = storage_backend.delete_category(
            _tenant_storage_category(category, owner["tenant_id"]), force=force
        )
    except ValueError as exc:
        log_audit_event(
            "delete_category", category=safe_category, status="conflict", detail=str(exc)
        )
        raise HTTPException(status_code=409, detail=str(exc))

    if not deleted:
        log_audit_event("delete_category", category=safe_category, status="not_found")
        raise HTTPException(status_code=404, detail=f"Category not found: {category}")

    metadata_repository.delete_folder(safe_category, tenant_id=owner["tenant_id"])

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
def search_chunks(request: SearchRequest, owner: dict = Depends(require_admin_key)) -> SearchResponse:
    """
    Run the hybrid retrieval pipeline (app/retrieval/retriever.py) for
    `query` and return its top `top_k` chunks, most relevant first,
    scoped to the caller's tenant.

    Only searches chunks that have made it to pgvector - i.e. from
    documents already `Indexed` (see GET /documents). Pass `category`
    to restrict the search to one category (including its subfolders).
    """

    results = retrieve(
        request.query, top_k=request.top_k, category=request.category, tenant_id=owner["tenant_id"]
    )

    return SearchResponse(
        query=request.query,
        results=[SearchResultChunk(**result) for result in results],
    )


@app.post(
    "/research/ask",
    response_model=OwnerResearchResponse,
    dependencies=[Depends(require_admin_key)],
)
async def owner_research_ask(request: OwnerResearchRequest, owner: dict = Depends(require_admin_key)) -> OwnerResearchResponse:
    """
    Real legal research for an authenticated Owner/Attorney/Paralegal:
    the same retrieval -> citation-locked, Claude-or-template answer
    generation End Users already get from POST /end-user/query/stream
    (app/analysis/answer_generation.py's stream_grounded_answer()) -
    not a second implementation, the identical one, reused here and
    returned as a single JSON response instead of Server-Sent Events.

    Always searches the Owner's library only (retrieve() with no
    Matter scoping - same as POST /search), so this can never surface
    another Matter's uploaded documents; `require_admin_key` above
    already enforces the caller holds a valid owner/attorney/paralegal
    JWT before this body ever runs.

    Honest-gap: if fewer than the Owner-configured minimum chunks are
    found, `answer` is the same "Insufficient information..." message
    the End User path returns, with an empty `sources` list - never a
    guess. Citation lock: every source in `sources` is exactly what
    retrieval returned for this request; the answer text itself is
    checked against that same set before being returned, with a
    template fallback on any ungrounded/fabricated citation (see
    app/analysis/answer_generation.py's _citations_are_grounded()).

    POST /search (raw chunks, no LLM call) is unchanged and still
    available for debugging/inspecting retrieval directly.
    """

    _enforce_plan_limit(owner["tenant_id"], RESOURCE_LLM_CALLS)

    settings = get_current_retrieval_settings(metadata_repository)
    resolved_top_k = request.top_k if request.top_k is not None else settings.top_k

    results = retrieve(
        request.query,
        top_k=resolved_top_k,
        category=request.category,
        score_threshold=settings.score_threshold,
        tenant_id=owner["tenant_id"],
    )

    sources_payload: list[dict] = []
    answer_pieces: list[str] = []

    async for event, payload in stream_grounded_answer(
        request.query, results, settings.min_chunks, purpose="owner_research", tenant_id=owner["tenant_id"]
    ):
        if event == "sources":
            sources_payload = payload["sources"]
        elif event == "answer_chunk":
            answer_pieces.append(payload["text"])
        elif event == "error":
            logger.warning("Owner research answer generation error for query %r: %s", request.query, payload["detail"])

    return OwnerResearchResponse(
        query=request.query,
        answer="".join(answer_pieces),
        sources=[OwnerResearchSource(**s) for s in sources_payload],
    )


@app.post(
    "/research/export",
    dependencies=[Depends(require_admin_key)],
)
def owner_research_export(request: OwnerResearchExportRequest) -> Response:
    """
    Render an already-returned POST /research/ask result as a
    downloadable .docx or .pdf file - same disclaimer mechanism as
    POST /compare/export (app/analysis/report_export.py). Never runs
    retrieval or Claude generation itself; only formats the exact
    query/answer/sources the client already has, so the exported file
    can never say something different from what was shown on screen.
    """

    disclaimer_text = get_current_disclaimer_text(metadata_repository)
    sources = [source.model_dump() for source in request.sources]

    if request.format == "docx":
        content = build_owner_research_docx(request.query, request.answer, sources, disclaimer_text)
        media_type = DOCX_MEDIA_TYPE
        filename = "research-answer.docx"
    else:
        content = build_owner_research_pdf(request.query, request.answer, sources, disclaimer_text)
        media_type = PDF_MEDIA_TYPE
        filename = "research-answer.pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
@app.post(
    "/admin/matters/{matter_id}/research",
    response_model=OwnerResearchResponse,
    dependencies=[Depends(require_admin_key)],
)
async def matter_research_ask(
    matter_id: int, request: OwnerResearchRequest, owner: dict = Depends(require_admin_key)
) -> OwnerResearchResponse:
    """
    Real Matter-scoped research: the exact same citation-locked,
    Claude-or-template answer generation POST /research/ask already
    uses (app/analysis/answer_generation.py's stream_grounded_answer())
    - not a second RAG system, the identical one - fed
    retrieve_for_matter()'s results instead of retrieve()'s, so the
    answer draws on the Owner's library AND this Matter's own ingested
    documents (app/matter_rag/), never any other Matter's namespace.
    """

    ensure_matter_access(owner, matter_id, metadata_repository)
    _enforce_plan_limit(owner["tenant_id"], RESOURCE_LLM_CALLS)

    settings = get_current_retrieval_settings(metadata_repository)
    resolved_top_k = request.top_k if request.top_k is not None else settings.top_k

    results = retrieve_for_matter(
        request.query, matter_id, top_k=resolved_top_k, score_threshold=settings.score_threshold,
        tenant_id=owner["tenant_id"],
    )

    sources_payload: list[dict] = []
    answer_pieces: list[str] = []

    async for event, payload in stream_grounded_answer(
        request.query, results, settings.min_chunks, purpose="matter_research", matter_id=matter_id,
        tenant_id=owner["tenant_id"],
    ):
        if event == "sources":
            sources_payload = payload["sources"]
        elif event == "answer_chunk":
            answer_pieces.append(payload["text"])
        elif event == "error":
            logger.warning(
                "Matter %s research answer generation error for query %r: %s",
                matter_id, request.query, payload["detail"],
            )

    return OwnerResearchResponse(
        query=request.query,
        answer="".join(answer_pieces),
        sources=[OwnerResearchSource(**s) for s in sources_payload],
    )


@app.get(
    "/admin/matters/{matter_id}/intake-sessions/{session_id}/research-suggestions",
    response_model=MatterResearchSuggestionsResponse,
    dependencies=[Depends(require_admin_key)],
)
def matter_research_suggestions(
    matter_id: int, session_id: int, owner: dict = Depends(require_admin_key)
) -> MatterResearchSuggestionsResponse:
    """
    Retrieval-grounded research suggestions for one Matter's intake
    session - reuses app/report/rag_analysis.py's gather_fact_support()
    (the exact same per-fact retrieval + classification the Client
    Report already runs) fed this Matter's own facts, never a second
    RAG system. Kept entirely separate from POST
    /admin/matters/{matter_id}/research's citation-grounded answer -
    this endpoint never generates prose, only surfaces retrieval hits
    against real facts, explicitly labeled as suggestions rather than
    legal conclusions.
    """

    ensure_matter_access(owner, matter_id, metadata_repository)

    session = metadata_repository.get_intake_session_by_id(session_id)
    if session is None or session["matter_id"] != matter_id:
        raise HTTPException(status_code=404, detail="Intake session not found for this matter.")

    fact_texts: list[str] = []
    for uploaded_input in metadata_repository.list_uploaded_inputs(session_id):
        for info in metadata_repository.list_extracted_information(uploaded_input["id"]):
            if info["text"].strip():
                fact_texts.append(info["text"])

    for fact in metadata_repository.list_intake_facts(session_id):
        if fact["fact_value"].strip():
            fact_texts.append(f"{fact['fact_key']}: {fact['fact_value']}")

    fact_supports = (
        gather_fact_support(fact_texts, metadata_repository, matter_id=matter_id, tenant_id=owner["tenant_id"])
        if fact_texts else []
    )

    suggestions = [
        MatterResearchSuggestion(
            fact_text=fs.fact_text,
            classification=fs.classification,
            citations=[MatterResearchSuggestionCitation(**c) for c in fs.citations],
        )
        for fs in fact_supports
        if fs.classification in ("match", "partial_match")
    ]

    return MatterResearchSuggestionsResponse(intake_session_id=session_id, matter_id=matter_id, suggestions=suggestions)
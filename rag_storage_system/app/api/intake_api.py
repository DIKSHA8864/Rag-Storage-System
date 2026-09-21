"""
Client Intake API - Phase 3 foundation. Guided, resumable intake
sessions for a Matter (the same isolated End User identity Phase 2
introduced - see app/security/auth.py): upload documents/images/audio/
video/ZIP (app/multimodal/), track their processing asynchronously via
the existing Redis/RQ queue (app/jobs/intake_processing.py), and
generate a structured, attorney-review-framed report (app/report/) once
ready.

Client uploads are stored under INTAKE_STORAGE_PATH
(app/storage/__init__.py's get_intake_storage_backend()), a completely
separate root from the Owner's knowledge base - never mixed, never
served through the Owner's document endpoints.

Every endpoint here is scoped to the caller's own Matter (via
app/security/auth.py's current_matter, the same isolation
app/api/end_user_api.py's threads use) - a session_id, upload_id, or
report_id belonging to a different Matter always 404s rather than
leaking, exactly like get_thread()'s existing isolation check.

Endpoints:
    POST   /end-user/intake/sessions                       start a new intake session
    GET    /end-user/intake/sessions                        list this Matter's intake sessions
    GET    /end-user/intake/sessions/{id}                   get one session
    POST   /end-user/intake/sessions/{id}/uploads            upload a file, enqueue processing
    GET    /end-user/intake/uploads/{upload_id}              poll one upload's processing status/extracted content
    GET    /end-user/intake/sessions/{id}/timeline           full audit trail for one session
    POST   /end-user/intake/sessions/{id}/report             build and store a structured report
    GET    /end-user/intake/reports/{report_id}/download     download a generated report
"""

import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.schemas import (
    ExtractedInformationInfo,
    IntakeSessionCreateRequest,
    IntakeSessionInfo,
    IntakeSessionListResponse,
    IntakeTimelineResponse,
    ReportGenerateRequest,
    ReportInfo,
    TimelineEventInfo,
    UploadedInputDetailResponse,
    UploadedInputInfo,
    UploadedInputQueuedResponse,
)
from app.jobs.intake_processing import run_intake_processing_job
from app.jobs.queue import get_job_queue
from app.multimodal.models import media_type_for_extension
from app.multimodal.validation import validate_intake_file
from app.report.builder import build_structured_report
from app.report.docx_renderer import DocxReportRenderer
from app.report.image_renderer import ImageReportRenderer
from app.report.pdf_renderer import PdfReportRenderer
from app.security.auth import current_matter, require_end_user_key
from app.api.intake_common import get_owned_intake_session as _get_owned_session
router = APIRouter(
    prefix="/end-user/intake",
    tags=["end-user-intake"],
    dependencies=[Depends(require_end_user_key)],
)

_RENDERERS = {
    "docx": DocxReportRenderer,
    "pdf": PdfReportRenderer,
    "image": ImageReportRenderer,
}

_EXTENSION_TO_MEDIA_TYPE = {
    "docx": DocxReportRenderer.media_type,
    "pdf": PdfReportRenderer.media_type,
    "png": "image/png",
    "zip": "application/zip",
}


def _session_info(session: dict) -> IntakeSessionInfo:
    return IntakeSessionInfo(
        id=session["id"],
        matter_id=session["matter_id"],
        thread_id=session.get("thread_id"),
        title=session["title"],
        status=session["status"],
        created_at=str(session["created_at"]),
        updated_at=str(session["updated_at"]),
    )


def _uploaded_input_info(row: dict) -> UploadedInputInfo:
    return UploadedInputInfo(
        id=row["id"],
        intake_session_id=row["intake_session_id"],
        original_filename=row["original_filename"],
        media_type=row["media_type"],
        size=row["size"],
        processing_status=row["processing_status"],
        status_detail=row.get("status_detail"),
        created_at=str(row["created_at"]),
    )



@router.post("/sessions", response_model=IntakeSessionInfo)
def create_intake_session(
    request: IntakeSessionCreateRequest, matter: dict = Depends(current_matter)
) -> IntakeSessionInfo:
    from app.api import storage_api

    repo = storage_api.metadata_repository

    if request.thread_id is not None and repo.get_thread(request.thread_id, matter["id"]) is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    session = repo.create_intake_session(matter["id"], request.title, thread_id=request.thread_id)
    repo.add_timeline_event(session["id"], "session_created", f"Intake session '{request.title}' created.")

    return _session_info(session)


@router.get("/sessions", response_model=IntakeSessionListResponse)
def list_intake_sessions(matter: dict = Depends(current_matter)) -> IntakeSessionListResponse:
    from app.api import storage_api

    sessions = storage_api.metadata_repository.list_intake_sessions(matter["id"])
    return IntakeSessionListResponse(sessions=[_session_info(s) for s in sessions])


@router.get("/sessions/{session_id}", response_model=IntakeSessionInfo)
def get_intake_session(session_id: int, matter: dict = Depends(current_matter)) -> IntakeSessionInfo:
    from app.api import storage_api

    session = _get_owned_session(storage_api.metadata_repository, session_id, matter)
    return _session_info(session)


@router.post("/sessions/{session_id}/uploads", response_model=UploadedInputQueuedResponse)
async def upload_intake_input(
    session_id: int,
    file: UploadFile = File(...),
    matter: dict = Depends(current_matter),
) -> UploadedInputQueuedResponse:
    """
    Upload one document/image/audio/video file, or a ZIP of several, to
    an intake session. Stored under INTAKE_STORAGE_PATH (never the
    Owner's knowledge base), validated the same way Owner uploads are
    (app/multimodal/validation.py, the intake-specific extension/size
    limits), then processed asynchronously (app/jobs/intake_processing.py)
    so a large file never blocks this request.
    """

    from app.api import storage_api
    from app.storage import get_intake_storage_backend

    session = _get_owned_session(storage_api.metadata_repository, session_id, matter)

    filename = file.filename or "unnamed"
    data = await file.read()
    await file.close()

    is_valid, reason = validate_intake_file(filename, len(data))
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid upload: {reason}")

    media_type = media_type_for_extension(Path(filename).suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

    storage_backend = get_intake_storage_backend()
    category = f"session_{session_id}"
    storage_backend.create_category(category)
    result = storage_backend.save(category, filename, io.BytesIO(data))

    uploaded_input = storage_api.metadata_repository.create_uploaded_input(
        intake_session_id=session_id,
        original_filename=filename,
        stored_category=result["category"],
        stored_filename=result["stored_filename"],
        media_type=media_type.value,
        size=result["size"],
        sha256=result["sha256"],
    )

    storage_api.metadata_repository.add_timeline_event(
        session_id, "input_uploaded", f"'{filename}' uploaded ({media_type.value})."
    )

    # Pass the exact repository/storage-backend instances explicitly
    # (same as POST /process -> run_processing_job in storage_api.py)
    # rather than letting the job resolve its own default factories -
    # otherwise tests that monkeypatch these attributes on storage_api/
    # app.storage would have the job silently write to the real
    # production database/storage instead of the test's isolated ones.
    job = get_job_queue().enqueue(
        run_intake_processing_job, uploaded_input["id"], storage_api.metadata_repository, storage_backend
    )

    return UploadedInputQueuedResponse(uploaded_input=_uploaded_input_info(uploaded_input), job_id=job.id)


@router.get("/uploads/{upload_id}", response_model=UploadedInputDetailResponse)
def get_uploaded_input_detail(upload_id: int, matter: dict = Depends(current_matter)) -> UploadedInputDetailResponse:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    uploaded_input = repo.get_uploaded_input(upload_id)

    if uploaded_input is None or repo.get_intake_session(uploaded_input["intake_session_id"], matter["id"]) is None:
        raise HTTPException(status_code=404, detail="Uploaded input not found.")

    extracted = repo.list_extracted_information(upload_id)

    return UploadedInputDetailResponse(
        uploaded_input=_uploaded_input_info(uploaded_input),
        extracted_information=[
            ExtractedInformationInfo(
                id=row["id"],
                content_type=row["content_type"],
                text=row["text"],
                provider=row["provider"],
                is_mock=bool(row["is_mock"]),
                archive_member_filename=row.get("archive_member_filename"),
                created_at=str(row["created_at"]),
            )
            for row in extracted
        ],
    )


@router.get("/sessions/{session_id}/timeline", response_model=IntakeTimelineResponse)
def get_intake_timeline(session_id: int, matter: dict = Depends(current_matter)) -> IntakeTimelineResponse:
    from app.api import storage_api

    repo = storage_api.metadata_repository
    _get_owned_session(repo, session_id, matter)

    events = repo.list_timeline_events(session_id)
    return IntakeTimelineResponse(
        intake_session_id=session_id,
        events=[
            TimelineEventInfo(
                id=e["id"], event_type=e["event_type"], description=e["description"], created_at=str(e["created_at"])
            )
            for e in events
        ],
    )


@router.post("/sessions/{session_id}/report", response_model=ReportInfo)
def generate_intake_report(
    session_id: int, request: ReportGenerateRequest, matter: dict = Depends(current_matter)
) -> ReportInfo:
    """
    Build a StructuredReport from this session's timeline and extracted
    content (app/report/builder.py - a template summary, never an LLM
    formatting the final document) and render it with the requested
    format's ReportRenderer, then store the rendered file the same way
    uploads are stored (INTAKE_STORAGE_PATH, never the Owner's
    knowledge base).
    """

    from app.api import storage_api
    from app.storage import get_intake_storage_backend

    repo = storage_api.metadata_repository
    _get_owned_session(repo, session_id, matter)

    renderer_cls = _RENDERERS.get(request.format)
    if renderer_cls is None:
        raise HTTPException(status_code=400, detail="`format` must be 'docx', 'pdf', or 'image'.")

    structured_report = build_structured_report(session_id, matter["name"], repo)

    renderer = renderer_cls()
    content = renderer.render(structured_report)

    storage_backend = get_intake_storage_backend()
    category = f"session_{session_id}/reports"
    storage_backend.create_category(category)
    filename = f"report_{session_id}.{renderer.file_extension}"
    stored = storage_backend.save(category, filename, io.BytesIO(content))

    report = repo.create_report(session_id, request.format, stored["category"], stored["stored_filename"])
    repo.add_timeline_event(session_id, "report_generated", f"{request.format.upper()} report generated.")
    repo.create_report_review(report["id"])

    return ReportInfo(id=report["id"], intake_session_id=session_id, format=report["format"], created_at=str(report["created_at"]))


@router.get("/reports/{report_id}/download")
def download_intake_report(report_id: int, matter: dict = Depends(current_matter)) -> Response:
    from app.api import storage_api
    from app.storage import get_intake_storage_backend

    repo = storage_api.metadata_repository
    report = repo.get_report(report_id)

    if report is None or repo.get_intake_session(report["intake_session_id"], matter["id"]) is None:
        raise HTTPException(status_code=404, detail="Report not found.")

    review = repo.get_report_review(report["id"])
    if review is None or review["status"] != "approved":
        raise HTTPException(
            status_code=403,
            detail="This report has not yet been approved by the Owner/attorney for release.",
        )
    storage_backend = get_intake_storage_backend()
    with storage_backend.open_file(report["stored_category"], report["stored_filename"]) as f:
        content = f.read()

    extension = Path(report["stored_filename"]).suffix.lstrip(".")
    media_type = _EXTENSION_TO_MEDIA_TYPE.get(extension, "application/octet-stream")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report_{report_id}.{extension}"'},
    )

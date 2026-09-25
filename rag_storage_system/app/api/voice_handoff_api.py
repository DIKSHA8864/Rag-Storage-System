"""
Voice interviewing and "Talk to a person" (Blueprint Phase 5).

Voice: the interview's questions are read aloud in the client's browser
(speech synthesis - nothing leaves the device). A spoken answer is
transcribed here with the firm's own configured speech-to-text
(STT_PROVIDER, e.g. local Whisper). The text goes back to the client to
check and edit, and only what they then send is recorded. The recording
itself is not stored.

Talk to a person: a client can ask for a human at any point; the request
lands in the firm's queue (Admin -> Requests), optionally with an email to
HANDOFF_NOTIFY_EMAILS, and staff claim and close it.

    GET  /end-user/intake/voice                                     is voice answering available?
    POST /end-user/intake/sessions/{id}/interview/transcribe          audio -> text for the client to review
    GET  /end-user/handoff                                          the caller's latest request
    POST /end-user/handoff                                          ask for a person
    GET  /admin/handoffs?status=open                                the organization's queue
    POST /admin/handoffs/{id}/claim | /close
"""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.intake_common import get_owned_intake_session
from app.api.schemas import (
    HandoffCloseRequest,
    HandoffCreateRequest,
    HandoffInfo,
    HandoffListResponse,
    TranscriptionResponse,
    VoiceCapabilities,
)
from app.security.auth import current_matter, require_admin_key, require_end_user_key
from app.security.virus_scan import ScannerUnavailable, scan_bytes
from config.settings import get_settings

logger = logging.getLogger(__name__)

end_user_router = APIRouter(prefix="/end-user", tags=["end-user-voice-handoff"], dependencies=[Depends(require_end_user_key)])
admin_router = APIRouter(prefix="/admin", tags=["handoffs"], dependencies=[Depends(require_admin_key)])

MAX_ANSWER_AUDIO_BYTES = 15 * 1024 * 1024  # a few minutes of speech
_AUDIO_EXTENSIONS = {".webm", ".weba", ".ogg", ".wav", ".m4a", ".mp3", ".mp4"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _repo():
    from app.api import storage_api

    return storage_api.metadata_repository


def _stt_available() -> bool:
    return get_settings().stt_provider not in ("", "mock")


def _info(row: dict) -> HandoffInfo:
    return HandoffInfo(
        id=row["id"], matter_id=row["matter_id"], intake_session_id=row.get("intake_session_id"),
        contact_method=row["contact_method"], contact_value=row["contact_value"], preferred_time=row.get("preferred_time"),
        message=row.get("message"), language=row.get("language"), status=row["status"], claimed_by=row.get("claimed_by"),
        closed_note=row.get("closed_note"), created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
    )


# ----------------------------------------------------------------------
# Voice
# ----------------------------------------------------------------------

@end_user_router.get("/intake/voice", response_model=VoiceCapabilities)
def voice_capabilities() -> VoiceCapabilities:
    return VoiceCapabilities(speech_to_text=_stt_available())


@end_user_router.post("/intake/sessions/{session_id}/interview/transcribe", response_model=TranscriptionResponse)
async def transcribe_answer(
    session_id: int, file: UploadFile = File(...), matter: dict = Depends(current_matter)
) -> TranscriptionResponse:
    from app.multimodal.speech_to_text import get_stt_provider

    get_owned_intake_session(_repo(), session_id, matter)
    if not _stt_available():
        raise HTTPException(status_code=409, detail="Voice answers aren't set up here yet - please type your answer.")

    filename = Path(file.filename or "answer.webm").name
    data = await file.read()
    await file.close()
    if Path(filename).suffix.lower() not in _AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="That isn't a supported audio recording.")
    if not data or len(data) > MAX_ANSWER_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="The recording is empty or too long - please keep answers to a few minutes.")
    try:
        if not scan_bytes(data).clean:
            raise HTTPException(status_code=400, detail="This recording could not be accepted.")
    except ScannerUnavailable:
        raise HTTPException(status_code=503, detail="Please try again in a few minutes, or type your answer.")

    try:
        text, is_mock = get_stt_provider().transcribe(data, filename)
    except Exception:
        logger.exception("Transcribing a spoken answer failed")
        raise HTTPException(status_code=502, detail="Your answer couldn't be transcribed - please try again or type it.")
    if is_mock:
        raise HTTPException(status_code=409, detail="Voice answers aren't set up here yet - please type your answer.")
    return TranscriptionResponse(text=text.strip())


# ----------------------------------------------------------------------
# Talk to a person - client side
# ----------------------------------------------------------------------

@end_user_router.get("/handoff", response_model=HandoffInfo | None)
def my_handoff(matter: dict = Depends(current_matter)) -> HandoffInfo | None:
    row = _repo().latest_handoff_for_matter(matter["id"], matter.get("end_user_id"))
    return _info(row) if row else None


@end_user_router.post("/handoff", response_model=HandoffInfo)
def request_handoff(body: HandoffCreateRequest, matter: dict = Depends(current_matter)) -> HandoffInfo:
    repo = _repo()
    contact = body.contact_value.strip()
    if body.contact_method == "email" and not _EMAIL.match(contact):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if body.contact_method in ("phone", "video") and not 7 <= len(re.sub(r"\D", "", contact)) <= 20:
        raise HTTPException(status_code=400, detail="Please enter a valid phone number.")

    session_id = None
    if body.intake_session_id is not None:
        session_id = get_owned_intake_session(repo, body.intake_session_id, matter)["id"]

    # One request at a time: asking again while one is open just returns it.
    latest = repo.latest_handoff_for_matter(matter["id"], matter.get("end_user_id"))
    if latest and latest["status"] in ("open", "claimed"):
        return _info(latest)

    session_matter_id = repo.get_intake_session_by_id(session_id)["matter_id"] if session_id else matter["id"]
    row = repo.create_handoff_request(
        matter.get("tenant_id", 1), session_matter_id, session_id, matter.get("end_user_id"), body.contact_method, contact,
        (body.preferred_time or "").strip() or None, (body.message or "").strip() or None, body.language,
    )
    if session_id:
        repo.add_timeline_event(session_id, "handoff_requested", f"Client asked to talk to a person ({body.contact_method}).")
    _notify_staff(row)
    return _info(row)


def _notify_staff(row: dict) -> None:
    recipients = [e.strip() for e in get_settings().handoff_notify_emails.split(",") if e.strip()]
    if not recipients:
        return
    from app.notifications.email_sender import get_email_sender

    body = (
        "A client asked to talk to a person.\n\n"
        f"Contact: {row['contact_method']} - {row['contact_value']}\n"
        f"Best time: {row.get('preferred_time') or '-'}\n"
        f"Message: {row.get('message') or '-'}\n\n"
        f"Open Admin -> Requests to claim it (request #{row['id']})."
    )
    for recipient in recipients:
        try:
            get_email_sender().send(recipient, "Client asked to talk to a person", body)
        except Exception:
            logger.exception("Could not email handoff request #%s to staff", row["id"])


# ----------------------------------------------------------------------
# Talk to a person - staff side
# ----------------------------------------------------------------------

@admin_router.get("/handoffs", response_model=HandoffListResponse)
def list_handoffs(status: str | None = None, owner: dict = Depends(require_admin_key)) -> HandoffListResponse:
    if status is not None and status not in ("open", "claimed", "closed"):
        raise HTTPException(status_code=400, detail="status must be open, claimed or closed.")
    rows = _repo().list_handoff_requests(owner["tenant_id"], status)
    open_count = sum(1 for r in _repo().list_handoff_requests(owner["tenant_id"], "open"))
    return HandoffListResponse(requests=[_info(r) for r in rows], open_count=open_count)


def _owned(request_id: int, owner: dict) -> dict:
    row = _repo().get_handoff_request(request_id, owner["tenant_id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    return row


@admin_router.post("/handoffs/{request_id}/claim", response_model=HandoffInfo)
def claim_handoff(request_id: int, owner: dict = Depends(require_admin_key)) -> HandoffInfo:
    row = _owned(request_id, owner)
    if row["status"] == "closed":
        raise HTTPException(status_code=409, detail="This request is already closed.")
    if row["status"] == "claimed" and row.get("claimed_by") != owner.get("email"):
        raise HTTPException(status_code=409, detail=f"Already claimed by {row.get('claimed_by')}.")
    return _info(_repo().update_handoff_request(request_id, owner["tenant_id"], "claimed", claimed_by=owner.get("email")))


@admin_router.post("/handoffs/{request_id}/close", response_model=HandoffInfo)
def close_handoff(request_id: int, body: HandoffCloseRequest, owner: dict = Depends(require_admin_key)) -> HandoffInfo:
    row = _owned(request_id, owner)
    if row["status"] == "closed":
        return _info(row)
    note = (body.note or "").strip() or None
    updated = _repo().update_handoff_request(
        request_id, owner["tenant_id"], "closed", claimed_by=row.get("claimed_by") or owner.get("email"), closed_note=note
    )
    if row.get("intake_session_id"):
        _repo().add_timeline_event(row["intake_session_id"], "handoff_closed", f"Talk-to-a-person request closed by {owner.get('email')}.")
    return _info(updated)

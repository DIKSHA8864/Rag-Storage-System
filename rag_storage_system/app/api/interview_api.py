"""
Guided Intake Engine API - a conversational, state-machine-driven
interview for a Client's intake session (app/intake_engine/). Layered
on top of app/api/intake_api.py's intake sessions: same Matter scope,
same isolation (a session belonging to another Matter 404s).

Endpoints:
    POST /end-user/intake/sessions/{id}/interview/start     start (or return the already-started) interview, get the opening prompt
    POST /end-user/intake/sessions/{id}/interview/message    send one answer, get the next prompt
    GET  /end-user/intake/sessions/{id}/interview            resume: full state + transcript
    GET  /end-user/intake/sessions/{id}/facts                structured facts extracted so far

The state machine itself (app/intake_engine/state_machine.py) is pure
and DB-free; app/intake_engine/engine.py is what actually persists
each turn: language selection -> terms acceptance -> mandatory sweep
-> protected activity -> closing narrative -> complete.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.intake_common import get_owned_intake_session
from app.api.schemas import (
    InterviewFactInfo,
    InterviewFactsResponse,
    InterviewMessageInfo,
    InterviewMessageRequest,
    InterviewMessageResponse,
    InterviewResumeResponse,
    InterviewStartResponse,
    InterviewStateInfo,
)
from app.intake_engine.engine import resume_interview, start_interview, submit_message
from app.security.auth import current_matter, require_end_user_key

router = APIRouter(
    prefix="/end-user/intake",
    tags=["end-user-intake-interview"],
    dependencies=[Depends(require_end_user_key)],
)


def _state_info(row: dict) -> InterviewStateInfo:
    return InterviewStateInfo(
        intake_session_id=row["intake_session_id"],
        language=row.get("language"),
        terms_accepted_at=str(row["terms_accepted_at"]) if row.get("terms_accepted_at") else None,
        terms_version=row.get("terms_version"),
        current_state=row["current_state"],
        current_step_index=row["current_step_index"],
        mandatory_sweep_completed=bool(row["mandatory_sweep_completed"]),
    )


@router.post("/sessions/{session_id}/interview/start", response_model=InterviewStartResponse)
def start_intake_interview(session_id: int, matter: dict = Depends(current_matter)) -> InterviewStartResponse:
    """Start the guided interview, or return its current state unchanged if one is already in progress."""

    from app.api import storage_api

    repo = storage_api.metadata_repository
    get_owned_intake_session(repo, session_id, matter)

    state = start_interview(session_id, repo)
    messages = repo.list_intake_messages(session_id)
    opening_prompt = messages[-1]["content"] if messages else ""

    return InterviewStartResponse(state=_state_info(state), prompt=opening_prompt)


@router.post("/sessions/{session_id}/interview/message", response_model=InterviewMessageResponse)
def send_intake_interview_message(
    session_id: int, request: InterviewMessageRequest, matter: dict = Depends(current_matter)
) -> InterviewMessageResponse:
    """Submit one answer and advance the state machine."""

    from app.api import storage_api

    repo = storage_api.metadata_repository
    get_owned_intake_session(repo, session_id, matter)

    try:
        result = submit_message(session_id, request.message, repo)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return InterviewMessageResponse(
        state=_state_info(result["state"]), reply=result["reply"], error=result["error"], done=result["done"]
    )


@router.get("/sessions/{session_id}/interview", response_model=InterviewResumeResponse)
def resume_intake_interview(session_id: int, matter: dict = Depends(current_matter)) -> InterviewResumeResponse:
    """Resume: the full current state and transcript, so a reconnecting Client can continue with POST .../message."""

    from app.api import storage_api

    repo = storage_api.metadata_repository
    get_owned_intake_session(repo, session_id, matter)

    result = resume_interview(session_id, repo)
    if result["state"] is None:
        raise HTTPException(status_code=404, detail="Interview not started for this session.")

    return InterviewResumeResponse(
        state=_state_info(result["state"]),
        messages=[
            InterviewMessageInfo(id=m["id"], role=m["role"], content=m["content"], created_at=str(m["created_at"]))
            for m in result["messages"]
        ],
    )


@router.get("/sessions/{session_id}/facts", response_model=InterviewFactsResponse)
def get_intake_facts(session_id: int, matter: dict = Depends(current_matter)) -> InterviewFactsResponse:
    """Structured facts extracted so far - mandatory sweep answers, protected-activity answers, and the closing narrative."""

    from app.api import storage_api

    repo = storage_api.metadata_repository
    get_owned_intake_session(repo, session_id, matter)

    facts = repo.list_intake_facts(session_id)

    return InterviewFactsResponse(
        intake_session_id=session_id,
        facts=[
            InterviewFactInfo(
                id=f["id"], category=f["category"], fact_key=f["fact_key"], fact_value=f["fact_value"],
                created_at=str(f["created_at"]),
            )
            for f in facts
        ],
    )
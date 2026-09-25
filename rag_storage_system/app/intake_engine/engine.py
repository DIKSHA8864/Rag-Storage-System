"""
Orchestrates the Guided Intake Engine against the database - the only
module here that touches MetadataRepository. app/intake_engine/state_machine.py
stays pure/DB-free so it can be unit-tested directly (see
tests/test_intake_engine.py); this module is what
app/api/interview_api.py actually calls.

New interviews run flow 2 (see state_machine.py): the organization's
checklist is frozen onto the interview when it starts, follow-up
questions are generated once from the story (app/intake_engine/follow_ups.py)
and stored so resuming asks the same ones, and terms acceptance is
recorded with its time, version and the client's IP address.
"""

from datetime import date, datetime, timezone
from typing import Optional

from app.intake_engine import timeline
from app.intake_engine.follow_ups import generate_follow_up_questions
from app.intake_engine.i18n import TERMS_VERSION
from app.intake_engine.mandatory_sweep import checklist_snapshot, questions_from_snapshot
from app.intake_engine.models import FLOW_V2, InterviewContext, InterviewState, StateMachineResult
from app.intake_engine.state_machine import advance, first_prompt
from app.metadata.base import MetadataRepository

_BEFORE_SWEEP = {
    InterviewState.LANGUAGE_SELECTION.value, InterviewState.TERMS_ACCEPTANCE.value, InterviewState.STORY.value,
    InterviewState.FOLLOW_UP.value, InterviewState.MANDATORY_SWEEP.value,
}


def start_interview(intake_session_id: int, metadata_repository: MetadataRepository, tenant_id: int = 1) -> dict:
    """
    Create (or return the existing) interview_state row for this
    session and record the opening bilingual prompt as the first
    assistant message. Safe to call again on a session that already
    has an interview in progress - see resume_interview() for reading
    it back without restarting anything.
    """

    existing = metadata_repository.get_interview_state(intake_session_id)
    if existing is not None:
        return existing

    metadata_repository.create_interview_state(intake_session_id)
    metadata_repository.set_interview_extras(
        intake_session_id, flow_version=FLOW_V2,
        checklist_snapshot=checklist_snapshot(metadata_repository, tenant_id),
    )
    metadata_repository.add_intake_message(intake_session_id, "assistant", first_prompt())

    return metadata_repository.get_interview_state(intake_session_id)


def resume_interview(intake_session_id: int, metadata_repository: MetadataRepository) -> dict:
    """Full state + transcript for reconnecting to an in-progress (or completed) interview."""

    state = metadata_repository.get_interview_state(intake_session_id)
    messages = metadata_repository.list_intake_messages(intake_session_id)

    return {"state": state, "messages": messages}


def context_from_state(state_row: dict, metadata_repository: Optional[MetadataRepository] = None) -> InterviewContext:
    """The state machine's view of a stored interview_state row (+ the key dates already answered, when a repository is given)."""

    recorded_dates = {}
    if metadata_repository is not None and state_row["current_state"] == InterviewState.TIMELINE.value:
        for fact in metadata_repository.list_intake_facts(state_row["intake_session_id"]):
            if fact["category"] == "timeline":
                recorded_dates[fact["fact_key"]] = timeline.recorded_value(fact["fact_value"])

    return InterviewContext(
        language=state_row["language"],
        terms_accepted=bool(state_row["terms_accepted_at"]),
        current_state=state_row["current_state"],
        current_step_index=state_row["current_step_index"],
        flow_version=state_row.get("flow_version") or 1,
        checklist=questions_from_snapshot(state_row.get("checklist_snapshot")),
        follow_ups=state_row.get("follow_up_questions"),
        recorded_dates=recorded_dates,
        today=date.today(),
    )


def submit_message(
    intake_session_id: int, user_input: str, metadata_repository: MetadataRepository,
    tenant_id: int = 1, client_ip: Optional[str] = None,
) -> dict:
    """
    Apply one user turn: record the user's message, run it through the
    state machine, persist whatever it decided (fact, timeline entry,
    terms-acceptance timestamp + IP, follow-up questions, new state),
    record the assistant's reply, and return both.
    """

    state_row = metadata_repository.get_interview_state(intake_session_id)
    if state_row is None:
        raise ValueError(f"No interview started for intake session {intake_session_id}. Call start first.")

    metadata_repository.add_intake_message(intake_session_id, "user", user_input)

    context = context_from_state(state_row, metadata_repository)

    # The one non-pure step: follow-ups are generated from the story
    # before the state machine applies it, and stored even when empty so
    # the story turn is never re-generated on resume.
    if context.current_state == InterviewState.STORY.value and user_input.strip() and context.follow_ups is None:
        follow_ups = generate_follow_up_questions(user_input.strip(), context.language, tenant_id)
        metadata_repository.set_interview_extras(intake_session_id, follow_up_questions=follow_ups)
        context.follow_ups = follow_ups

    result: StateMachineResult = advance(context, user_input)

    terms_accepted_at = state_row["terms_accepted_at"]
    terms_version = state_row["terms_version"]
    if not context.terms_accepted and result.context.terms_accepted:
        terms_accepted_at = datetime.now(timezone.utc).isoformat()
        terms_version = TERMS_VERSION
        if client_ip:
            metadata_repository.set_interview_extras(intake_session_id, terms_accepted_ip=client_ip[:64])
        metadata_repository.add_timeline_event(
            intake_session_id, "terms_accepted",
            f"Terms {TERMS_VERSION} accepted" + (f" from IP {client_ip[:64]}" if client_ip else "") + ".",
        )

    mandatory_sweep_completed = result.context.current_state not in _BEFORE_SWEEP

    metadata_repository.update_interview_state(
        intake_session_id,
        language=result.context.language,
        current_state=result.context.current_state,
        current_step_index=result.context.current_step_index,
        terms_accepted_at=terms_accepted_at,
        terms_version=terms_version,
        mandatory_sweep_completed=mandatory_sweep_completed,
    )

    if not result.error and result.recorded_fact_key is not None:
        category = _category_for_state(context.current_state)
        metadata_repository.add_intake_fact(
            intake_session_id, category, result.recorded_fact_key, result.recorded_fact_value
        )
        metadata_repository.add_timeline_event(
            intake_session_id, "fact_recorded", f"{result.recorded_fact_key}: {result.recorded_fact_value}"
        )

    metadata_repository.add_intake_message(intake_session_id, "assistant", result.prompt)

    if result.done:
        metadata_repository.add_timeline_event(
            intake_session_id, "interview_completed", "Guided intake interview completed."
        )

    return {
        "state": metadata_repository.get_interview_state(intake_session_id),
        "reply": result.prompt, "error": result.error, "done": result.done,
    }


def _category_for_state(state_value: str) -> str:
    return {
        InterviewState.MANDATORY_SWEEP.value: "mandatory_sweep",
        InterviewState.PROTECTED_ACTIVITY.value: "protected_activity",
        InterviewState.FOLLOW_UP.value: "follow_up",
        InterviewState.TIMELINE.value: "timeline",
        InterviewState.DOCUMENTS.value: "documents",
    }.get(state_value, "general")

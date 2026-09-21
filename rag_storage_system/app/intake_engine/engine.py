"""
Orchestrates the Guided Intake Engine against the database - the only
module here that touches MetadataRepository. app/intake_engine/state_machine.py
stays pure/DB-free so it can be unit-tested directly (see
tests/test_intake_engine.py); this module is what
app/api/interview_api.py actually calls.
"""

from datetime import datetime, timezone

from app.intake_engine.i18n import TERMS_VERSION
from app.intake_engine.models import InterviewContext, InterviewState, StateMachineResult
from app.intake_engine.state_machine import advance, first_prompt
from app.metadata.base import MetadataRepository


def start_interview(intake_session_id: int, metadata_repository: MetadataRepository) -> dict:
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

    state = metadata_repository.create_interview_state(intake_session_id)
    metadata_repository.add_intake_message(intake_session_id, "assistant", first_prompt())

    return state


def resume_interview(intake_session_id: int, metadata_repository: MetadataRepository) -> dict:
    """Full state + transcript for reconnecting to an in-progress (or completed) interview."""

    state = metadata_repository.get_interview_state(intake_session_id)
    messages = metadata_repository.list_intake_messages(intake_session_id)

    return {"state": state, "messages": messages}


def submit_message(intake_session_id: int, user_input: str, metadata_repository: MetadataRepository) -> dict:
    """
    Apply one user turn: record the user's message, run it through the
    state machine, persist whatever it decided (fact, timeline entry,
    terms-acceptance timestamp, new state), record the assistant's
    reply, and return both.
    """

    state_row = metadata_repository.get_interview_state(intake_session_id)
    if state_row is None:
        raise ValueError(f"No interview started for intake session {intake_session_id}. Call start first.")

    metadata_repository.add_intake_message(intake_session_id, "user", user_input)

    context = InterviewContext(
        language=state_row["language"],
        terms_accepted=bool(state_row["terms_accepted_at"]),
        current_state=state_row["current_state"],
        current_step_index=state_row["current_step_index"],
    )

    result: StateMachineResult = advance(context, user_input)

    terms_accepted_at = state_row["terms_accepted_at"]
    terms_version = state_row["terms_version"]
    if not context.terms_accepted and result.context.terms_accepted:
        terms_accepted_at = datetime.now(timezone.utc).isoformat()
        terms_version = TERMS_VERSION

    mandatory_sweep_completed = result.context.current_state not in (
        InterviewState.LANGUAGE_SELECTION.value,
        InterviewState.TERMS_ACCEPTANCE.value,
        InterviewState.MANDATORY_SWEEP.value,
    )

    updated_state = metadata_repository.update_interview_state(
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

    return {"state": updated_state, "reply": result.prompt, "error": result.error, "done": result.done}


def _category_for_state(state_value: str) -> str:
    if state_value == InterviewState.MANDATORY_SWEEP.value:
        return "mandatory_sweep"
    if state_value == InterviewState.PROTECTED_ACTIVITY.value:
        return "protected_activity"
    return "general"
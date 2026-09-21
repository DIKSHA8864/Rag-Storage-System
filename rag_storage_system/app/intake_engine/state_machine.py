"""
Pure guided-intake state machine - no DB access here (app/intake_engine/engine.py
persists what this module decides). Given the current InterviewContext
and the caller's raw text, decides what (if anything) gets recorded
and what state/prompt comes next: language selection -> terms
acceptance -> the mandatory ancillary sweep -> the protected activity
section -> a closing narrative -> complete. Kept side-effect-free so
the whole flow can be tested without a database or HTTP layer (see
tests/test_intake_engine.py).
"""

from app.intake_engine.i18n import normalize_language, normalize_terms_acceptance, prompt_text
from app.intake_engine.mandatory_sweep import MANDATORY_SWEEP_QUESTIONS
from app.intake_engine.models import InterviewContext, InterviewState, StateMachineResult
from app.intake_engine.protected_activity import PROTECTED_ACTIVITY_QUESTIONS


def first_prompt() -> str:
    """The very first message shown, before any language is known - always bilingual."""

    return prompt_text(InterviewState.LANGUAGE_SELECTION, language=None)


def advance(context: InterviewContext, user_input: str) -> StateMachineResult:
    """Apply one user turn to `context` and return the result. Never mutates `context` - always returns a new one."""

    state = InterviewState(context.current_state)

    if state == InterviewState.LANGUAGE_SELECTION:
        return _handle_language_selection(context, user_input)
    if state == InterviewState.TERMS_ACCEPTANCE:
        return _handle_terms_acceptance(context, user_input)
    if state == InterviewState.MANDATORY_SWEEP:
        return _handle_fixed_question_block(
            context, user_input, MANDATORY_SWEEP_QUESTIONS, InterviewState.PROTECTED_ACTIVITY
        )
    if state == InterviewState.PROTECTED_ACTIVITY:
        return _handle_fixed_question_block(
            context, user_input, PROTECTED_ACTIVITY_QUESTIONS, InterviewState.GENERAL_NARRATIVE
        )
    if state == InterviewState.GENERAL_NARRATIVE:
        return _handle_general_narrative(context, user_input)

    # COMPLETE - nothing more to record; keep repeating the closing prompt.
    return StateMachineResult(context=context, prompt=prompt_text(InterviewState.COMPLETE, context.language), done=True)


def _handle_language_selection(context: InterviewContext, user_input: str) -> StateMachineResult:
    language = normalize_language(user_input)

    if language is None:
        return StateMachineResult(context=context, prompt=prompt_text(InterviewState.LANGUAGE_SELECTION, None), error=True)

    next_context = InterviewContext(
        language=language, terms_accepted=context.terms_accepted,
        current_state=InterviewState.TERMS_ACCEPTANCE.value, current_step_index=0,
    )
    return StateMachineResult(context=next_context, prompt=prompt_text(InterviewState.TERMS_ACCEPTANCE, language))


def _handle_terms_acceptance(context: InterviewContext, user_input: str) -> StateMachineResult:
    if not normalize_terms_acceptance(user_input, context.language):
        return StateMachineResult(
            context=context, prompt=prompt_text(InterviewState.TERMS_ACCEPTANCE, context.language), error=True
        )

    next_context = InterviewContext(
        language=context.language, terms_accepted=True,
        current_state=InterviewState.MANDATORY_SWEEP.value, current_step_index=0,
    )
    return StateMachineResult(context=next_context, prompt=MANDATORY_SWEEP_QUESTIONS[0].text(context.language))


def _handle_fixed_question_block(context, user_input, questions, next_state) -> StateMachineResult:
    index = context.current_step_index
    question = questions[index]

    # Every question in these blocks is mandatory - a blank answer is
    # re-prompted rather than silently advancing.
    if not user_input or not user_input.strip():
        return StateMachineResult(context=context, prompt=question.text(context.language), error=True)

    recorded_value = user_input.strip()
    next_index = index + 1

    if next_index < len(questions):
        next_context = InterviewContext(
            language=context.language, terms_accepted=context.terms_accepted,
            current_state=context.current_state, current_step_index=next_index,
        )
        return StateMachineResult(
            context=next_context, prompt=questions[next_index].text(context.language),
            recorded_fact_key=question.key, recorded_fact_value=recorded_value,
        )

    next_context = InterviewContext(
        language=context.language, terms_accepted=context.terms_accepted,
        current_state=next_state.value, current_step_index=0,
    )

    next_prompt = (
        PROTECTED_ACTIVITY_QUESTIONS[0].text(context.language)
        if next_state == InterviewState.PROTECTED_ACTIVITY
        else prompt_text(next_state, context.language)
    )

    return StateMachineResult(
        context=next_context, prompt=next_prompt,
        recorded_fact_key=question.key, recorded_fact_value=recorded_value,
    )


def _handle_general_narrative(context: InterviewContext, user_input: str) -> StateMachineResult:
    if not user_input or not user_input.strip():
        return StateMachineResult(
            context=context, prompt=prompt_text(InterviewState.GENERAL_NARRATIVE, context.language), error=True
        )

    next_context = InterviewContext(
        language=context.language, terms_accepted=context.terms_accepted,
        current_state=InterviewState.COMPLETE.value, current_step_index=0,
    )
    return StateMachineResult(
        context=next_context, prompt=prompt_text(InterviewState.COMPLETE, context.language),
        recorded_fact_key="narrative_summary", recorded_fact_value=user_input.strip(), done=True,
    )
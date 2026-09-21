"""
Tests for the pure Guided Intake Engine state machine
(app/intake_engine/state_machine.py) - no database, no HTTP, so the
full English and Spanish conversation flows and the mandatory sweep
can be verified as plain function calls.
"""

from app.intake_engine.mandatory_sweep import MANDATORY_SWEEP_QUESTIONS
from app.intake_engine.models import InterviewContext, InterviewState
from app.intake_engine.protected_activity import PROTECTED_ACTIVITY_QUESTIONS
from app.intake_engine.state_machine import advance, first_prompt


def _initial_context() -> InterviewContext:
    return InterviewContext(language=None, terms_accepted=False, current_state=InterviewState.LANGUAGE_SELECTION.value, current_step_index=0)


def test_first_prompt_is_bilingual():
    prompt = first_prompt()
    assert "English" in prompt
    assert "Espa" in prompt


def test_english_language_selection_advances_to_terms():
    result = advance(_initial_context(), "english")

    assert result.context.language == "en"
    assert result.context.current_state == InterviewState.TERMS_ACCEPTANCE.value
    assert result.error is False


def test_spanish_language_selection_advances_to_terms_in_spanish():
    result = advance(_initial_context(), "espanol")

    assert result.context.language == "es"
    assert result.context.current_state == InterviewState.TERMS_ACCEPTANCE.value
    assert "Acepto" in result.prompt


def test_unrecognized_language_reprompts_without_advancing():
    result = advance(_initial_context(), "french")

    assert result.error is True
    assert result.context.current_state == InterviewState.LANGUAGE_SELECTION.value


def test_terms_rejection_reprompts_without_advancing():
    context = InterviewContext(language="en", terms_accepted=False, current_state=InterviewState.TERMS_ACCEPTANCE.value, current_step_index=0)

    result = advance(context, "no thanks")

    assert result.error is True
    assert result.context.current_state == InterviewState.TERMS_ACCEPTANCE.value
    assert result.context.terms_accepted is False


def test_terms_acceptance_in_english_advances_to_mandatory_sweep():
    context = InterviewContext(language="en", terms_accepted=False, current_state=InterviewState.TERMS_ACCEPTANCE.value, current_step_index=0)

    result = advance(context, "I agree")

    assert result.context.terms_accepted is True
    assert result.context.current_state == InterviewState.MANDATORY_SWEEP.value
    assert result.prompt == MANDATORY_SWEEP_QUESTIONS[0].prompt_en


def test_terms_acceptance_in_spanish_accepts_acepto():
    context = InterviewContext(language="es", terms_accepted=False, current_state=InterviewState.TERMS_ACCEPTANCE.value, current_step_index=0)

    result = advance(context, "Acepto")

    assert result.context.terms_accepted is True
    assert result.context.current_state == InterviewState.MANDATORY_SWEEP.value
    assert result.prompt == MANDATORY_SWEEP_QUESTIONS[0].prompt_es


def test_mandatory_sweep_cannot_be_skipped_with_a_blank_answer():
    context = InterviewContext(language="en", terms_accepted=True, current_state=InterviewState.MANDATORY_SWEEP.value, current_step_index=0)

    result = advance(context, "   ")

    assert result.error is True
    assert result.context.current_step_index == 0
    assert result.recorded_fact_key is None


def test_mandatory_sweep_walks_every_question_in_order_then_moves_to_protected_activity():
    context = InterviewContext(language="en", terms_accepted=True, current_state=InterviewState.MANDATORY_SWEEP.value, current_step_index=0)

    for index, question in enumerate(MANDATORY_SWEEP_QUESTIONS):
        result = advance(context, f"answer {index}")
        assert result.recorded_fact_key == question.key
        assert result.recorded_fact_value == f"answer {index}"
        context = result.context

    assert context.current_state == InterviewState.PROTECTED_ACTIVITY.value
    assert context.current_step_index == 0
    assert result.prompt == PROTECTED_ACTIVITY_QUESTIONS[0].prompt_en


def test_protected_activity_walks_every_question_then_moves_to_general_narrative():
    context = InterviewContext(language="en", terms_accepted=True, current_state=InterviewState.PROTECTED_ACTIVITY.value, current_step_index=0)

    for index, question in enumerate(PROTECTED_ACTIVITY_QUESTIONS):
        result = advance(context, f"pa answer {index}")
        assert result.recorded_fact_key == question.key
        context = result.context

    assert context.current_state == InterviewState.GENERAL_NARRATIVE.value


def test_general_narrative_completes_the_interview():
    context = InterviewContext(language="en", terms_accepted=True, current_state=InterviewState.GENERAL_NARRATIVE.value, current_step_index=0)

    result = advance(context, "My employer fired me after I reported a safety issue.")

    assert result.done is True
    assert result.context.current_state == InterviewState.COMPLETE.value
    assert result.recorded_fact_key == "narrative_summary"


def test_complete_state_keeps_repeating_the_closing_message():
    context = InterviewContext(language="en", terms_accepted=True, current_state=InterviewState.COMPLETE.value, current_step_index=0)

    result = advance(context, "anything")

    assert result.done is True
    assert result.context.current_state == InterviewState.COMPLETE.value


def test_mandatory_sweep_covers_all_blueprint_required_topics():
    """AshiLegal Blueprint Phase 3: the ancillary sweep must ask about
    timely wages, overtime, meal/rest breaks, wage statements, protected
    complaints/whistleblowing, leave, and accommodation - regardless of
    the client's stated issue - so none of these are ever missed."""

    required_topics = {
        "timely_wages",
        "overtime",
        "meal_rest_breaks",
        "wage_statements",
        "protected_complaints",
        "leave",
        "accommodation",
    }

    sweep_keys = {question.key for question in MANDATORY_SWEEP_QUESTIONS}

    assert required_topics.issubset(sweep_keys)

    for question in MANDATORY_SWEEP_QUESTIONS:
        assert question.prompt_en.strip()
        assert question.prompt_es.strip()
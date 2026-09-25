"""
Pure guided-intake state machine - no DB access here (app/intake_engine/engine.py
persists what this module decides, and does the one non-pure step -
generating follow-up questions - before calling advance()). Given the
current InterviewContext and the caller's raw text, decides what (if
anything) gets recorded and what state/prompt comes next.

Flow 2 (every new interview - Blueprint Phase 3: "story first, then
guided follow-ups"): language -> terms -> the client's story ->
follow-up questions generated from the story and the firm's question
frameworks -> the ancillary checklist sweep (owner-editable) ->
protected activity -> key dates (validated for chronology) -> documents
-> complete.

Flow 1 (interviews started before flow 2 existed, kept so they finish
the way they started): language -> terms -> sweep -> protected activity
-> closing narrative -> complete.

Kept side-effect-free so the whole flow can be tested without a
database or HTTP layer (see tests/test_intake_engine.py).
"""

from dataclasses import replace
from datetime import date
from typing import Optional

from app.intake_engine import timeline
from app.intake_engine.i18n import normalize_language, normalize_terms_acceptance, prompt_text
from app.intake_engine.mandatory_sweep import MANDATORY_SWEEP_QUESTIONS
from app.intake_engine.models import FLOW_V1, FLOW_V2, InterviewContext, InterviewState, StateMachineResult
from app.intake_engine.protected_activity import PROTECTED_ACTIVITY_QUESTIONS

# At most this many follow-ups are generated (app/intake_engine/follow_ups.py);
# also the estimate shown in "Question X of Y" until they exist.
MAX_FOLLOW_UPS = 4

_SKIP_WORDS = {"skip", "pass", "omitir", "saltar", "siguiente"}


def first_prompt() -> str:
    """The very first message shown, before any language is known - always bilingual."""

    return prompt_text(InterviewState.LANGUAGE_SELECTION, language=None)


TOTAL_QUESTIONS = len(MANDATORY_SWEEP_QUESTIONS) + len(PROTECTED_ACTIVITY_QUESTIONS) + 1  # flow 1: + the closing narrative


def checklist_of(context: InterviewContext) -> list:
    return context.checklist if context.checklist is not None else MANDATORY_SWEEP_QUESTIONS


def total_questions(context: InterviewContext) -> int:
    if context.flow_version == FLOW_V1:
        return TOTAL_QUESTIONS
    follow_up_count = len(context.follow_ups) if context.follow_ups is not None else MAX_FOLLOW_UPS
    return (
        1 + follow_up_count + len(checklist_of(context)) + len(PROTECTED_ACTIVITY_QUESTIONS)
        + len(timeline.TIMELINE_QUESTIONS) + 1
    )


def question_number(context: InterviewContext) -> Optional[int]:
    """
    1-based position of the question currently being asked, out of
    total_questions() - so the client always sees how far along they
    are. None before the questions start (language/terms) and once it's
    complete.
    """

    state = InterviewState(context.current_state)
    index = context.current_step_index

    if context.flow_version == FLOW_V1:
        if state == InterviewState.MANDATORY_SWEEP:
            return index + 1
        if state == InterviewState.PROTECTED_ACTIVITY:
            return len(MANDATORY_SWEEP_QUESTIONS) + index + 1
        if state == InterviewState.GENERAL_NARRATIVE:
            return TOTAL_QUESTIONS
        return None

    follow_up_count = len(context.follow_ups) if context.follow_ups is not None else MAX_FOLLOW_UPS
    offsets = {
        InterviewState.STORY: 0,
        InterviewState.FOLLOW_UP: 1,
        InterviewState.MANDATORY_SWEEP: 1 + follow_up_count,
        InterviewState.PROTECTED_ACTIVITY: 1 + follow_up_count + len(checklist_of(context)),
        InterviewState.TIMELINE: 1 + follow_up_count + len(checklist_of(context)) + len(PROTECTED_ACTIVITY_QUESTIONS),
    }
    if state in offsets:
        return offsets[state] + index + 1
    if state == InterviewState.DOCUMENTS:
        return total_questions(context)
    return None


def current_question_key(context: InterviewContext) -> Optional[str]:
    """Which question is on screen (e.g. 'overtime', 'date_hired', 'follow_up_2') - lets the UI offer the right quick replies."""

    state = InterviewState(context.current_state)
    index = context.current_step_index
    if state == InterviewState.MANDATORY_SWEEP:
        questions = checklist_of(context)
        return questions[index].key if index < len(questions) else None
    if state == InterviewState.PROTECTED_ACTIVITY:
        return PROTECTED_ACTIVITY_QUESTIONS[index].key
    if state == InterviewState.TIMELINE:
        return timeline.TIMELINE_QUESTIONS[index].key
    if state == InterviewState.FOLLOW_UP:
        return f"follow_up_{index + 1}"
    if state in (InterviewState.STORY, InterviewState.DOCUMENTS, InterviewState.GENERAL_NARRATIVE):
        return state.value
    return None


def current_prompt(context: InterviewContext) -> str:
    """The question for `context` as it stands (used to re-ask after a rejected answer)."""

    state = InterviewState(context.current_state)
    language = context.language
    index = context.current_step_index
    if state == InterviewState.MANDATORY_SWEEP:
        return checklist_of(context)[index].text(language)
    if state == InterviewState.PROTECTED_ACTIVITY:
        return PROTECTED_ACTIVITY_QUESTIONS[index].text(language)
    if state == InterviewState.TIMELINE:
        return timeline.TIMELINE_QUESTIONS[index].text(language)
    if state == InterviewState.FOLLOW_UP:
        return (context.follow_ups or [""])[index]
    return prompt_text(state, language)


def advance(context: InterviewContext, user_input: str) -> StateMachineResult:
    """
    Apply one user turn to `context` and return the result. Never mutates `context` - always returns a new one.

    In flow 2 the STORY turn needs context.follow_ups already set (the
    engine generates them from this same input first); [] means no
    follow-ups and goes straight to the checklist.
    """

    state = InterviewState(context.current_state)

    if state == InterviewState.LANGUAGE_SELECTION:
        return _handle_language_selection(context, user_input)
    if state == InterviewState.TERMS_ACCEPTANCE:
        return _handle_terms_acceptance(context, user_input)
    if state == InterviewState.STORY:
        return _handle_story(context, user_input)
    if state == InterviewState.FOLLOW_UP:
        return _handle_follow_up(context, user_input)
    if state == InterviewState.MANDATORY_SWEEP:
        return _handle_fixed_question_block(context, user_input, checklist_of(context), "mandatory_sweep")
    if state == InterviewState.PROTECTED_ACTIVITY:
        return _handle_fixed_question_block(context, user_input, PROTECTED_ACTIVITY_QUESTIONS, "protected_activity")
    if state == InterviewState.TIMELINE:
        return _handle_timeline(context, user_input)
    if state == InterviewState.DOCUMENTS:
        return _handle_closing(context, user_input, "documents_available", InterviewState.DOCUMENTS)
    if state == InterviewState.GENERAL_NARRATIVE:
        return _handle_closing(context, user_input, "narrative_summary", InterviewState.GENERAL_NARRATIVE)

    # COMPLETE - nothing more to record; keep repeating the closing prompt.
    return StateMachineResult(context=context, prompt=prompt_text(InterviewState.COMPLETE, context.language), done=True)


# ----------------------------------------------------------------------
# Transitions
# ----------------------------------------------------------------------

def _enter(context: InterviewContext, state: InterviewState, intro: Optional[str] = None) -> tuple[InterviewContext, str]:
    """Move to the first question of `state` (skipping empty sections) and return (context, prompt)."""

    language = context.language
    if state == InterviewState.FOLLOW_UP and not context.follow_ups:
        return _enter(context, InterviewState.MANDATORY_SWEEP, intro="checklist_intro")
    if state == InterviewState.MANDATORY_SWEEP and not checklist_of(context):
        return _enter(context, InterviewState.PROTECTED_ACTIVITY)

    next_context = replace(context, current_state=state.value, current_step_index=0)
    prompt = current_prompt(next_context)
    if intro:
        prompt = f"{prompt_text(intro, language)}\n\n{prompt}"
    return next_context, prompt


def _after(context: InterviewContext, block: str) -> tuple[InterviewContext, str]:
    """Where the interview goes once `block` is finished, for this flow."""

    if block == "mandatory_sweep":
        return _enter(context, InterviewState.PROTECTED_ACTIVITY)
    if block == "protected_activity":
        if context.flow_version == FLOW_V1:
            return _enter(context, InterviewState.GENERAL_NARRATIVE)
        return _enter(context, InterviewState.TIMELINE, intro="timeline_intro")
    if block == "timeline":
        return _enter(context, InterviewState.DOCUMENTS)
    raise ValueError(f"Unknown block: {block}")


def _blank(user_input: str) -> bool:
    return not user_input or not user_input.strip()


def _handle_language_selection(context: InterviewContext, user_input: str) -> StateMachineResult:
    language = normalize_language(user_input)

    if language is None:
        return StateMachineResult(context=context, prompt=prompt_text(InterviewState.LANGUAGE_SELECTION, None), error=True)

    next_context = replace(context, language=language, current_state=InterviewState.TERMS_ACCEPTANCE.value, current_step_index=0)
    return StateMachineResult(context=next_context, prompt=prompt_text(InterviewState.TERMS_ACCEPTANCE, language))


def _handle_terms_acceptance(context: InterviewContext, user_input: str) -> StateMachineResult:
    if not normalize_terms_acceptance(user_input, context.language):
        return StateMachineResult(
            context=context, prompt=prompt_text(InterviewState.TERMS_ACCEPTANCE, context.language), error=True
        )

    accepted = replace(context, terms_accepted=True)
    first_state = InterviewState.STORY if context.flow_version == FLOW_V2 else InterviewState.MANDATORY_SWEEP
    next_context, prompt = _enter(accepted, first_state)
    return StateMachineResult(context=next_context, prompt=prompt)


def _handle_story(context: InterviewContext, user_input: str) -> StateMachineResult:
    if _blank(user_input):
        return StateMachineResult(context=context, prompt=current_prompt(context), error=True)
    if context.follow_ups is None:
        raise ValueError("Follow-up questions must be generated before the story turn is applied.")

    next_context, prompt = _enter(context, InterviewState.FOLLOW_UP, intro="follow_up_intro")
    return StateMachineResult(
        context=next_context, prompt=prompt, recorded_fact_key="client_story", recorded_fact_value=user_input.strip()
    )


def _handle_follow_up(context: InterviewContext, user_input: str) -> StateMachineResult:
    if _blank(user_input):
        return StateMachineResult(context=context, prompt=current_prompt(context), error=True)

    index = context.current_step_index
    question = context.follow_ups[index]
    answer = user_input.strip()
    if answer.lower().strip(" .!") in _SKIP_WORDS:
        answer = "(skipped)"

    if index + 1 < len(context.follow_ups):
        next_context = replace(context, current_step_index=index + 1)
        prompt = current_prompt(next_context)
    else:
        next_context, prompt = _enter(context, InterviewState.MANDATORY_SWEEP, intro="checklist_intro")

    return StateMachineResult(
        context=next_context, prompt=prompt,
        recorded_fact_key=f"follow_up_{index + 1}", recorded_fact_value=f"Q: {question}\nA: {answer}",
    )


def _handle_fixed_question_block(context: InterviewContext, user_input: str, questions: list, block: str) -> StateMachineResult:
    index = context.current_step_index
    question = questions[index]

    # Every question in these blocks is mandatory - a blank answer is
    # re-prompted rather than silently advancing.
    if _blank(user_input):
        return StateMachineResult(context=context, prompt=question.text(context.language), error=True)

    if index + 1 < len(questions):
        next_context = replace(context, current_step_index=index + 1)
        prompt = questions[index + 1].text(context.language)
    else:
        next_context, prompt = _after(context, block)

    return StateMachineResult(
        context=next_context, prompt=prompt,
        recorded_fact_key=question.key, recorded_fact_value=user_input.strip(),
    )


def _handle_timeline(context: InterviewContext, user_input: str) -> StateMachineResult:
    index = context.current_step_index
    question = timeline.TIMELINE_QUESTIONS[index]
    answer = timeline.parse_date_answer(user_input or "", context.language)
    problem = timeline.answer_error(
        question, answer, context.recorded_dates, context.today or date.today(), context.language
    )
    if problem:
        return StateMachineResult(context=context, prompt=f"{problem}\n\n{question.text(context.language)}", error=True)

    recorded_dates = {**context.recorded_dates, question.key: answer}
    advanced = replace(context, recorded_dates=recorded_dates)
    if index + 1 < len(timeline.TIMELINE_QUESTIONS):
        next_context = replace(advanced, current_step_index=index + 1)
        prompt = current_prompt(next_context)
    else:
        next_context, prompt = _after(advanced, "timeline")

    return StateMachineResult(
        context=next_context, prompt=prompt,
        recorded_fact_key=question.key, recorded_fact_value=f"{answer.value} (answer: {user_input.strip()})",
    )


def _handle_closing(context: InterviewContext, user_input: str, fact_key: str, state: InterviewState) -> StateMachineResult:
    if _blank(user_input):
        return StateMachineResult(context=context, prompt=prompt_text(state, context.language), error=True)

    next_context = replace(context, current_state=InterviewState.COMPLETE.value, current_step_index=0)
    return StateMachineResult(
        context=next_context, prompt=prompt_text(InterviewState.COMPLETE, context.language),
        recorded_fact_key=fact_key, recorded_fact_value=user_input.strip(), done=True,
    )

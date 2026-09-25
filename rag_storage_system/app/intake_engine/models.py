"""Shared types for the Guided Intake Engine (app/intake_engine/state_machine.py, engine.py)."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class InterviewState(str, Enum):
    LANGUAGE_SELECTION = "language_selection"
    TERMS_ACCEPTANCE = "terms_acceptance"
    STORY = "story"                    # flow v2: the client's own account comes first
    FOLLOW_UP = "follow_up"            # flow v2: questions generated from the story + the firm's frameworks
    MANDATORY_SWEEP = "mandatory_sweep"
    PROTECTED_ACTIVITY = "protected_activity"
    TIMELINE = "timeline"              # flow v2: key dates, validated for chronology
    DOCUMENTS = "documents"            # flow v2: what supporting documents the client has
    GENERAL_NARRATIVE = "general_narrative"  # flow v1 only (closing narrative)
    COMPLETE = "complete"


# Flow 1: terms -> sweep -> protected activity -> closing narrative.
# Flow 2 (every interview started after migration 0023): terms -> story ->
# follow-ups -> checklist sweep -> protected activity -> key dates ->
# documents. An interview keeps the flow it started on.
FLOW_V1, FLOW_V2 = 1, 2


@dataclass
class InterviewContext:
    """The persisted slice of interview_state the state machine needs to decide the next step."""

    language: Optional[str]
    terms_accepted: bool
    current_state: str
    current_step_index: int
    flow_version: int = FLOW_V1
    # The checklist sweep this interview asks (objects with .key and
    # .text(language)); None = the built-in MANDATORY_SWEEP_QUESTIONS.
    checklist: Optional[list] = None
    # Follow-up questions generated from the story; None = not generated yet.
    follow_ups: Optional[list[str]] = None
    # Key dates answered so far (timeline.DateAnswer by question key), for chronology checks.
    recorded_dates: dict = field(default_factory=dict)
    today: Optional[date] = None


@dataclass
class StateMachineResult:
    """
    What advance() decided for one turn: the new context, the next
    prompt, an optional fact to record, whether this turn was rejected
    (error - re-prompt without advancing), and whether it ended the
    interview (done).
    """

    context: InterviewContext
    prompt: str
    recorded_fact_key: Optional[str] = None
    recorded_fact_value: Optional[str] = None
    error: bool = False
    done: bool = False
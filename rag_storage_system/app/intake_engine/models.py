"""Shared types for the Guided Intake Engine (app/intake_engine/state_machine.py, engine.py)."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class InterviewState(str, Enum):
    LANGUAGE_SELECTION = "language_selection"
    TERMS_ACCEPTANCE = "terms_acceptance"
    MANDATORY_SWEEP = "mandatory_sweep"
    PROTECTED_ACTIVITY = "protected_activity"
    GENERAL_NARRATIVE = "general_narrative"
    COMPLETE = "complete"


@dataclass
class InterviewContext:
    """The persisted slice of interview_state the state machine needs to decide the next step."""

    language: Optional[str]
    terms_accepted: bool
    current_state: str
    current_step_index: int


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
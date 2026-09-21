"""
Fixed, mandatory questions asked immediately after terms acceptance,
before anything else - the "ancillary sweep" every guided intake must
run through regardless of the client's actual legal issue, so a
safety risk, an imminent deadline, or existing representation is never
missed just because the conversation went straight to the client's
main story. None of these can be skipped (see
app/intake_engine/state_machine.py's _handle_fixed_question_block()).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SweepQuestion:
    key: str
    prompt_en: str
    prompt_es: str

    def text(self, language: Optional[str]) -> str:
        return self.prompt_es if language == "es" else self.prompt_en


MANDATORY_SWEEP_QUESTIONS: list[SweepQuestion] = [
    SweepQuestion(
        key="immediate_safety_risk",
        prompt_en="Is there any immediate safety risk or emergency we should know about right now?",
        prompt_es="Existe algun riesgo de seguridad inmediato o emergencia que debamos conocer ahora mismo?",
    ),
    SweepQuestion(
        key="upcoming_deadline",
        prompt_en="Are there any upcoming legal deadlines or court dates related to this matter?",
        prompt_es="Hay algun plazo legal o fecha de audiencia proxima relacionada con este asunto?",
    ),
    SweepQuestion(
        key="other_representation",
        prompt_en="Are you currently represented by another attorney for this matter?",
        prompt_es="Actualmente cuenta con otro abogado que lo represente en este asunto?",
    ),
]
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
    # AshiLegal Blueprint Phase 3 required ancillary-sweep topics - every
    # intake must ask about each of these regardless of the client's
    # stated issue, so a wage-and-hour or retaliation problem is never
    # missed just because the client didn't bring it up unprompted.
    SweepQuestion(
        key="timely_wages",
        prompt_en="Were you always paid for all hours worked, and paid on time, including at the end of your employment?",
        prompt_es="Siempre le pagaron por todas las horas trabajadas, y a tiempo, incluyendo al finalizar su empleo?",
    ),
    SweepQuestion(
        key="overtime",
        prompt_en="Did you ever work more than 8 hours in a day or 40 hours in a week without receiving overtime pay?",
        prompt_es="Alguna vez trabajo mas de 8 horas en un dia o 40 horas en una semana sin recibir pago de tiempo extra?",
    ),
    SweepQuestion(
        key="meal_rest_breaks",
        prompt_en="Were you always provided the meal and rest breaks required by law during your shifts?",
        prompt_es="Siempre le proporcionaron los descansos para comer y descansar que exige la ley durante sus turnos?",
    ),
    SweepQuestion(
        key="wage_statements",
        prompt_en="Did you receive an accurate, itemized wage statement (pay stub) with every paycheck?",
        prompt_es="Recibio un comprobante de pago (talon de cheque) preciso y detallado con cada pago?",
    ),
    SweepQuestion(
        key="protected_complaints",
        prompt_en=(
            "Have you ever made a complaint - to your employer or to a government agency - "
            "about wages, safety, discrimination, or other workplace issues?"
        ),
        prompt_es=(
            "Alguna vez presento una queja, a su empleador o a una agencia gubernamental, "
            "sobre salarios, seguridad, discriminacion u otros problemas laborales?"
        ),
    ),
    SweepQuestion(
        key="leave",
        prompt_en="Have you ever requested or taken job-protected leave, such as medical, family, pregnancy, or disability leave?",
        prompt_es="Alguna vez solicito o tomo una licencia protegida por ley, como licencia medica, familiar, por embarazo o por discapacidad?",
    ),
    SweepQuestion(
        key="accommodation",
        prompt_en="Have you ever requested a workplace accommodation for a disability, medical condition, religious practice, or similar need?",
        prompt_es="Alguna vez solicito una adaptacion en el trabajo por una discapacidad, condicion medica, practica religiosa u otra necesidad similar?",
    ),
]

# ----------------------------------------------------------------------
# The owner-editable checklist (flow v2, /admin/intake/checklist)
# ----------------------------------------------------------------------

# Blueprint Phase 3's required ancillary-sweep topics: an owner can reword
# them but never switch them off (tests/test_phase3_blueprint_acceptance.py).
REQUIRED_CHECKLIST_KEYS = frozenset({
    "timely_wages", "overtime", "meal_rest_breaks", "wage_statements", "protected_complaints", "leave", "accommodation",
})


def default_checklist() -> list[dict]:
    return [
        {"key": q.key, "prompt_en": q.prompt_en, "prompt_es": q.prompt_es, "is_active": True, "required": q.key in REQUIRED_CHECKLIST_KEYS}
        for q in MANDATORY_SWEEP_QUESTIONS
    ]


def tenant_checklist(repository, tenant_id: int) -> list[dict]:
    """The organization's checklist (every row, active or not) - the built-in default until an owner saves one."""

    rows = repository.get_intake_checklist(tenant_id)
    if not rows:
        return default_checklist()
    return [
        {"key": r["key"], "prompt_en": r["prompt_en"], "prompt_es": r["prompt_es"], "is_active": bool(r["is_active"]),
         "required": r["key"] in REQUIRED_CHECKLIST_KEYS}
        for r in rows
    ]


def checklist_snapshot(repository, tenant_id: int) -> list[dict]:
    """The active questions, frozen onto a new interview so later edits don't shift an in-progress one."""

    return [
        {"key": item["key"], "prompt_en": item["prompt_en"], "prompt_es": item["prompt_es"]}
        for item in tenant_checklist(repository, tenant_id) if item["is_active"]
    ]


def questions_from_snapshot(snapshot: Optional[list[dict]]) -> Optional[list[SweepQuestion]]:
    if snapshot is None:
        return None
    return [SweepQuestion(key=item["key"], prompt_en=item["prompt_en"], prompt_es=item["prompt_es"]) for item in snapshot]

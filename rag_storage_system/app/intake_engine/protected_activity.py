"""
Fixed questions covering legally "protected activity" - conduct the
law shields from retaliation (reporting discrimination/harassment,
participating in an investigation, taking protected leave, union
activity, etc.). Asked as its own dedicated section, after the
mandatory sweep, so a potential retaliation claim is never missed just
because the client didn't think to mention it unprompted.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProtectedActivityQuestion:
    key: str
    prompt_en: str
    prompt_es: str

    def text(self, language: Optional[str]) -> str:
        return self.prompt_es if language == "es" else self.prompt_en


PROTECTED_ACTIVITY_QUESTIONS: list[ProtectedActivityQuestion] = [
    ProtectedActivityQuestion(
        key="reported_concern",
        prompt_en=(
            "Did you ever report, complain about, or oppose something you believed was "
            "illegal or improper (for example, discrimination, harassment, safety "
            "violations, or fraud)?"
        ),
        prompt_es=(
            "Alguna vez denuncio, se quejo o se opuso a algo que considero ilegal o "
            "indebido (por ejemplo, discriminacion, acoso, violaciones de seguridad o fraude)?"
        ),
    ),
    ProtectedActivityQuestion(
        key="participated_in_investigation",
        prompt_en=(
            "Did you ever participate in, or provide information for, an investigation, "
            "hearing, or legal proceeding?"
        ),
        prompt_es=(
            "Alguna vez participo, o proporciono informacion, en una investigacion, "
            "audiencia o procedimiento legal?"
        ),
    ),
    ProtectedActivityQuestion(
        key="exercised_legal_right",
        prompt_en=(
            "Did you ever request or take legally protected leave or accommodation, or "
            "exercise another legal right (for example, medical leave, disability "
            "accommodation, or union activity)?"
        ),
        prompt_es=(
            "Alguna vez solicito o tomo una licencia o adaptacion legalmente protegida, "
            "o ejercio otro derecho legal (por ejemplo, licencia medica, adaptacion por "
            "discapacidad o actividad sindical)?"
        ),
    ),
]
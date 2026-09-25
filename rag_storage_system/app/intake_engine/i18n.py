"""
Bilingual (English/Spanish - the only two languages Phase 3 supports)
text for the Guided Intake Engine (app/intake_engine/state_machine.py).
Every prompt keyed by InterviewState has both a version;
normalize_language()/normalize_terms_acceptance() turn a Client's
free-text answer into a value the state machine can branch on,
tolerant of common variants in either language.
"""

from typing import Optional

TERMS_VERSION = "2026-01"

TERMS_TEXT = {
    "en": (
        "Before we begin, please review: information you share here is used to "
        "evaluate your matter and is not shared outside this firm without your "
        "consent. This is not legal advice, and no attorney-client relationship "
        "is formed until the firm agrees to represent you. Reply 'I agree' to continue."
    ),
    "es": (
        "Antes de comenzar, tenga en cuenta: la informacion que comparta aqui se "
        "utiliza para evaluar su caso y no se comparte fuera de este despacho sin "
        "su consentimiento. Esto no constituye asesoria legal, y no se forma una "
        "relacion abogado-cliente hasta que el despacho acepte representarlo. "
        "Responda 'Acepto' para continuar."
    ),
}

_LANGUAGE_PROMPT = "Please select your language / Seleccione su idioma:\n1) English\n2) Espanol"

_STATE_PROMPTS = {
    "terms_acceptance": TERMS_TEXT,
    "general_narrative": {
        "en": "In your own words, please describe what happened and why you are seeking legal help.",
        "es": "En sus propias palabras, describa que sucedio y por que busca ayuda legal.",
    },
    "story": {
        "en": (
            "Please tell us what happened, in your own words and in as much detail as you can: "
            "who your employer is, what your job was, what went wrong, and when. "
            "Take your time - you can write as much as you need."
        ),
        "es": (
            "Por favor cuentenos que sucedio, en sus propias palabras y con el mayor detalle posible: "
            "quien es su empleador, cual era su trabajo, que salio mal y cuando. "
            "Tome su tiempo - puede escribir todo lo que necesite."
        ),
    },
    "follow_up_intro": {
        "en": "Thank you. A few questions about what you described:",
        "es": "Gracias. Algunas preguntas sobre lo que nos conto:",
    },
    "checklist_intro": {
        "en": "Thank you. Now some standard questions we ask everyone:",
        "es": "Gracias. Ahora algunas preguntas que hacemos a todos:",
    },
    "timeline_intro": {
        "en": "Almost done. A few key dates:",
        "es": "Ya casi terminamos. Algunas fechas importantes:",
    },
    "documents": {
        "en": (
            "Last question: what documents do you have that relate to this - for example pay stubs, "
            "your offer letter, emails or texts, write-ups, a termination letter, or photos? "
            "List what you have (or say 'none'). You can upload them in the Uploads panel."
        ),
        "es": (
            "Ultima pregunta: que documentos tiene relacionados con esto - por ejemplo talones de pago, "
            "su carta de oferta, correos o mensajes, amonestaciones, una carta de despido o fotos? "
            "Enumere lo que tenga (o diga 'ninguno'). Puede subirlos en el panel de archivos."
        ),
    },
    "complete": {
        "en": "Thank you. Your intake interview is complete and has been recorded for attorney review.",
        "es": "Gracias. Su entrevista de admision ha finalizado y ha sido registrada para revision de un abogado.",
    },
}

_LANGUAGE_ALIASES = {
    "en": {"en", "english", "1"},
    "es": {"es", "spanish", "espanol", "2"},
}

_TERMS_ACCEPTANCE_ALIASES = {
    "en": {"i agree", "agree", "yes", "y", "accept", "i accept"},
    "es": {"acepto", "si", "de acuerdo", "acepto los terminos"},
}


def normalize_language(raw: str) -> Optional[str]:
    value = (raw or "").strip().lower()
    for code, aliases in _LANGUAGE_ALIASES.items():
        if value in aliases:
            return code
    return None


def normalize_terms_acceptance(raw: str, language: Optional[str]) -> bool:
    value = (raw or "").strip().lower()
    aliases = _TERMS_ACCEPTANCE_ALIASES.get(language or "en", set()) | _TERMS_ACCEPTANCE_ALIASES["en"]
    return value in aliases


def prompt_text(state, language: Optional[str]) -> str:
    """`state` is an InterviewState or its string value."""

    state_value = state.value if hasattr(state, "value") else state

    if state_value == "language_selection":
        return _LANGUAGE_PROMPT

    prompts = _STATE_PROMPTS.get(state_value)
    if prompts is None:
        raise ValueError(f"No prompt text defined for state: {state_value}")

    return prompts.get(language or "en", prompts["en"])
"""
Key dates for the intake timeline (Blueprint Phase 3: "capture key dates
(hire, complaints, leave, termination)"; Work Plan M5: "validate dates and
chronology; flag gaps"). Pure - no database - like state_machine.py.

Answers are free text in English or Spanish: "April 2023", "03/15/2023",
"15 de marzo de 2023", "2021", or "don't know" / "none" / "still working
there". Each is normalized to its real precision ("2023-04", "2023-03-15",
"2021") so a month-only answer is never presented as an exact day.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from dateutil import parser as date_parser

KIND_DATE, KIND_UNKNOWN, KIND_NONE, KIND_STILL_EMPLOYED, KIND_INVALID = (
    "date", "unknown", "none", "still_employed", "invalid",
)


@dataclass(frozen=True)
class TimelineQuestion:
    key: str
    prompt_en: str
    prompt_es: str
    label_en: str
    allows_none: bool = False            # "none" / "never" is a real answer (e.g. no complaint made)
    allows_still_employed: bool = False  # for the last-day question

    def text(self, language: Optional[str]) -> str:
        return self.prompt_es if language == "es" else self.prompt_en


TIMELINE_QUESTIONS: list[TimelineQuestion] = [
    TimelineQuestion(
        key="date_hired",
        prompt_en="When did you start working for this employer? A month and year is fine (e.g. 'April 2023').",
        prompt_es="Cuando empezo a trabajar para este empleador? El mes y el ano son suficientes (ej. 'abril 2023').",
        label_en="Started working",
    ),
    TimelineQuestion(
        key="date_problem_started",
        prompt_en="When did the main problem you described first happen?",
        prompt_es="Cuando ocurrio por primera vez el problema principal que describio?",
        label_en="Problem first happened",
    ),
    TimelineQuestion(
        key="date_first_complaint",
        prompt_en="When did you first complain or report the problem to anyone? If you never did, say 'none'.",
        prompt_es="Cuando se quejo o reporto el problema por primera vez? Si nunca lo hizo, diga 'ninguna'.",
        label_en="First complaint or report",
        allows_none=True,
    ),
    TimelineQuestion(
        key="date_last_day",
        prompt_en="What was your last day of work there? If you still work there, say 'still working'.",
        prompt_es="Cual fue su ultimo dia de trabajo alli? Si todavia trabaja alli, diga 'sigo trabajando'.",
        label_en="Last day of work",
        allows_still_employed=True,
    ),
]

_UNKNOWN = {"don't know", "dont know", "do not know", "not sure", "unknown", "i don't know", "idk", "no se", "no lo se", "no estoy seguro", "no estoy segura", "desconozco"}
_NONE = {"none", "never", "no", "n/a", "na", "i didn't", "i did not", "ninguna", "ninguno", "nunca", "no me queje"}
_STILL = {"still working", "still work there", "still employed", "i still work there", "currently employed", "sigo trabajando", "todavia trabajo alli", "aun trabajo alli", "todavia trabajo"}

_SPANISH_MONTHS = {
    "enero": "January", "febrero": "February", "marzo": "March", "abril": "April", "mayo": "May", "junio": "June",
    "julio": "July", "agosto": "August", "septiembre": "September", "setiembre": "September", "octubre": "October",
    "noviembre": "November", "diciembre": "December",
}

_MESSAGES = {
    "unreadable": {
        "en": "I couldn't read that as a date. Please give at least a month and year (e.g. 'April 2023'), or say 'don't know'.",
        "es": "No pude entender esa fecha. Indique al menos el mes y el ano (ej. 'abril 2023'), o diga 'no se'.",
    },
    "future": {
        "en": "That date is in the future. Please check it and answer again.",
        "es": "Esa fecha esta en el futuro. Revisela y responda de nuevo.",
    },
    "order": {
        "en": "That date is before {other_label} ({other_value}). Please check it and answer again, or say 'don't know'.",
        "es": "Esa fecha es anterior a {other_label} ({other_value}). Revisela y responda de nuevo, o diga 'no se'.",
    },
}
_LABELS_EN = {
    "date_hired": "the date you started working",
    "date_problem_started": "the date the problem started",
    "date_first_complaint": "your first complaint",
    "date_last_day": "your last day",
}
_LABELS_ES = {
    "date_hired": "la fecha en que empezo a trabajar",
    "date_problem_started": "la fecha en que empezo el problema",
    "date_first_complaint": "su primera queja",
    "date_last_day": "su ultimo dia",
}


@dataclass(frozen=True)
class DateAnswer:
    kind: str
    value: Optional[str] = None  # normalized: "2023-04-15" | "2023-04" | "2023", or a word for non-dates
    earliest: Optional[date] = None  # first day the answer could mean - for chronology checks
    latest: Optional[date] = None    # last day it could mean


def _normalize_phrase(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().lower().replace("’", "'")).strip(" .!")


def parse_date_answer(raw: str, language: Optional[str]) -> DateAnswer:
    phrase = _normalize_phrase(raw or "")
    if not phrase:
        return DateAnswer(KIND_INVALID)
    if phrase in _UNKNOWN:
        return DateAnswer(KIND_UNKNOWN, "unknown")
    if phrase in _NONE:
        return DateAnswer(KIND_NONE, "none")
    if phrase in _STILL:
        return DateAnswer(KIND_STILL_EMPLOYED, "still employed")

    text = phrase
    for spanish, english in _SPANISH_MONTHS.items():
        text = re.sub(rf"\b{spanish}\b", english, text)
    text = re.sub(r"\bde(l)?\b", " ", text)

    try:
        first = date_parser.parse(text, default=datetime(1904, 1, 1), dayfirst=language == "es", fuzzy=False)
        second = date_parser.parse(text, default=datetime(1905, 2, 2), dayfirst=language == "es", fuzzy=False)
    except (ValueError, OverflowError):
        return DateAnswer(KIND_INVALID)

    has_year = first.year == second.year
    has_month = first.month == second.month
    has_day = first.day == second.day
    if not has_year:
        return DateAnswer(KIND_INVALID)

    year = first.year
    if has_month and has_day:
        exact = date(year, first.month, first.day)
        return DateAnswer(KIND_DATE, exact.isoformat(), exact, exact)
    if has_month:
        month_end = (date(year + (first.month == 12), first.month % 12 + 1, 1).toordinal() - 1)
        return DateAnswer(KIND_DATE, f"{year:04d}-{first.month:02d}", date(year, first.month, 1), date.fromordinal(month_end))
    return DateAnswer(KIND_DATE, f"{year:04d}", date(year, 1, 1), date(year, 12, 31))


def answer_error(question: TimelineQuestion, answer: DateAnswer, recorded: dict[str, DateAnswer], today: date, language: Optional[str]) -> Optional[str]:
    """None if `answer` is acceptable for `question` given the dates already recorded; else what to tell the client."""

    lang = "es" if language == "es" else "en"
    if answer.kind == KIND_INVALID:
        return _MESSAGES["unreadable"][lang]
    if answer.kind == KIND_NONE and not question.allows_none:
        return _MESSAGES["unreadable"][lang]
    if answer.kind == KIND_STILL_EMPLOYED and not question.allows_still_employed:
        return _MESSAGES["unreadable"][lang]
    if answer.kind != KIND_DATE:
        return None

    if answer.earliest > today:
        return _MESSAGES["future"][lang]

    # Everything in this timeline happens on or after the hire date; the
    # last day can't come before the problem started. Only a clear
    # contradiction is flagged - overlapping "April 2023" vs "2023" is fine.
    must_not_precede = {
        "date_problem_started": ["date_hired"],
        "date_first_complaint": ["date_hired"],
        "date_last_day": ["date_hired", "date_problem_started"],
    }.get(question.key, [])
    for other_key in must_not_precede:
        other = recorded.get(other_key)
        if other is not None and other.kind == KIND_DATE and answer.latest < other.earliest:
            label = (_LABELS_ES if lang == "es" else _LABELS_EN)[other_key]
            return _MESSAGES["order"][lang].format(other_label=label, other_value=other.value)
    return None


def recorded_value(stored: str) -> DateAnswer:
    """Re-read a fact_value written by the engine ("2023-04 (answer: April 2023)" / "unknown" / ...) for chronology checks."""

    token = (stored or "").split(" (answer:")[0].strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        exact = date.fromisoformat(token)
        return DateAnswer(KIND_DATE, token, exact, exact)
    if re.fullmatch(r"\d{4}-\d{2}", token):
        return _month(token)
    if re.fullmatch(r"\d{4}", token):
        year = int(token)
        return DateAnswer(KIND_DATE, token, date(year, 1, 1), date(year, 12, 31))
    return DateAnswer(KIND_UNKNOWN, token)


def _month(token: str) -> DateAnswer:
    year, month = (int(part) for part in token.split("-"))
    last = date(year + (month == 12), month % 12 + 1, 1).toordinal() - 1
    return DateAnswer(KIND_DATE, token, date(year, month, 1), date.fromordinal(last))

"""
The content of a complaint laid out as a pleading - attorney block,
court, caption, numbered allegations, prayer, signature - built once from
a ComplaintDraft and rendered either on California pleading paper
(pleading_paper.py) or into the firm's own Word template
(template_fill.py).

Same rules as the rest of app/complaint/: nothing is invented. Facts come
from the intake, authority from the curated cause-of-action library;
anything unknown (defendant, case number, relief, dates) stays a bracketed
placeholder for the attorney. Research suggestions are never part of the
pleading - they go on a separate "remove before filing" attorney page.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.complaint.schema import ComplaintDraft

_ORDINALS = [
    "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH",
    "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH", "FIFTEENTH",
]


def ordinal(n: int) -> str:
    return _ORDINALS[n - 1] if 1 <= n <= len(_ORDINALS) else f"{n}TH"


@dataclass
class PleadingBlock:
    kind: str  # "heading" | "subheading" | "numbered" | "text" | "signature"
    text: str
    number: Optional[int] = None


@dataclass
class PleadingContent:
    attorney_lines: list[str]
    court_lines: list[str]
    plaintiff: str
    defendant: str
    case_number: str
    title: str                # e.g. "COMPLAINT FOR DAMAGES" - also the footer title (CRC 2.110)
    causes_list: list[str]    # "1. FAILURE TO PAY OVERTIME" ... under the title in the caption
    body: list[PleadingBlock]
    attorney_notes: list[tuple[str, list[str]]] = field(default_factory=list)

    def placeholder_values(self) -> dict[str, str]:
        """{{name}} -> text, for the firm's own templates (template_fill.py)."""

        return {
            "attorney_block": "\n".join(self.attorney_lines),
            "court": "\n".join(self.court_lines),
            "plaintiff": self.plaintiff,
            "defendant": self.defendant,
            "case_number": self.case_number,
            "title": self.title,
            "causes": "\n".join(self.causes_list),
        }


def _or_placeholder(value: Optional[str], placeholder: str) -> str:
    value = (value or "").strip()
    return value if value else placeholder


def build_pleading_content(
    draft: ComplaintDraft,
    settings: Optional[dict],
    plaintiff: Optional[str] = None,
    defendant: Optional[str] = None,
    case_number: Optional[str] = None,
    county: Optional[str] = None,
) -> PleadingContent:
    settings = settings or {}

    attorney_name = _or_placeholder(settings.get("attorney_name"), "[ATTORNEY NAME]")
    bar_number = _or_placeholder(settings.get("bar_number"), "[STATE BAR NO.]")
    attorney_lines = [f"{attorney_name} (SBN {bar_number})"]
    attorney_lines.append(_or_placeholder(settings.get("firm_name"), "[FIRM NAME]"))
    attorney_lines += [line.strip() for line in (settings.get("address") or "[ADDRESS]").splitlines() if line.strip()]
    attorney_lines.append(f"Telephone: {_or_placeholder(settings.get('phone'), '[PHONE]')}")
    attorney_lines.append(f"Email: {_or_placeholder(settings.get('email'), '[EMAIL]')}")
    attorney_lines.append("")
    attorney_lines.append(f"Attorney for {_or_placeholder(settings.get('attorney_for'), 'Plaintiff')}")

    court_name = _or_placeholder(settings.get("court_name"), "SUPERIOR COURT OF THE STATE OF CALIFORNIA")
    county_name = _or_placeholder(county or settings.get("county"), "[COUNTY]")
    court_lines = [court_name.upper(), f"FOR THE COUNTY OF {county_name.upper()}"]

    plaintiff = _or_placeholder(plaintiff, "[PLAINTIFF NAME]")
    defendant = _or_placeholder(defendant, "[DEFENDANT NAME]")
    case_number = _or_placeholder(case_number, "[CASE NUMBER]")

    causes = draft.causes_of_action
    causes_list = [f"{i}. {cause.name.upper()}" for i, cause in enumerate(causes, start=1)]

    body: list[PleadingBlock] = []
    number = 0

    def allege(text: str) -> None:
        nonlocal number
        number += 1
        body.append(PleadingBlock("numbered", text, number))

    body.append(PleadingBlock("text", f"Plaintiff {plaintiff} alleges as follows:"))
    body.append(PleadingBlock("heading", "PARTIES"))
    allege(f"Plaintiff {plaintiff} is, and at all relevant times was, an individual. [CONFIRM RESIDENCE/COUNTY]")
    allege(f"Defendant {defendant} is, and at all relevant times was, [ENTITY TYPE AND PRINCIPAL PLACE OF BUSINESS].")
    allege("Plaintiff does not know the true names of the defendants sued as DOES 1 through 20 and will amend "
           "this complaint when they are ascertained. [ATTORNEY TO CONFIRM]")
    body.append(PleadingBlock("heading", "JURISDICTION AND VENUE"))
    allege(draft.jurisdiction_placeholder)
    last_general = number

    for index, cause in enumerate(causes, start=1):
        body.append(PleadingBlock("heading", f"{ordinal(index)} CAUSE OF ACTION"))
        body.append(PleadingBlock("subheading", f"({cause.name})"))
        body.append(PleadingBlock("subheading", f"(Against {defendant} and DOES 1 through 20)"))
        allege(f"Plaintiff incorporates by reference paragraphs 1 through {last_general} as though fully set forth here.")
        for element in cause.elements:
            if element.satisfied_by:
                allege(f"{element.description}: {element.satisfied_by}")
            else:
                allege(f"{element.description}: {element.placeholder}")
        allege(f"Authority: {cause.authority_citation}")

    body.append(PleadingBlock("heading", "PRAYER FOR RELIEF"))
    body.append(PleadingBlock("text", "WHEREFORE, Plaintiff prays for judgment against Defendants, and each of them, as follows:"))
    body.append(PleadingBlock("text", "1. [RELIEF TO BE SPECIFIED BY ATTORNEY];"))
    body.append(PleadingBlock("text", "2. For such other and further relief as the Court deems just and proper."))
    body.append(PleadingBlock("signature", "Dated: [DATE]"))
    body.append(PleadingBlock("signature", attorney_lines[1]))
    body.append(PleadingBlock("signature", ""))
    body.append(PleadingBlock("signature", "By: ______________________________"))
    body.append(PleadingBlock("signature", attorney_name))
    body.append(PleadingBlock("signature", attorney_lines[-1]))

    notes: list[tuple[str, list[str]]] = [("Attorney review", [draft.attorney_review_notice])]
    for cause in causes:
        if cause.research_suggestions:
            notes.append((
                f"{cause.name} - research suggestions (NOT cited authority - verify before relying on them)",
                [f"{r.filename} ({r.category}): {r.chunk_text}" for r in cause.research_suggestions],
            ))
    notes.append(("Disclaimer", [draft.disclaimer_text]))

    return PleadingContent(
        attorney_lines=attorney_lines, court_lines=court_lines, plaintiff=plaintiff, defendant=defendant,
        case_number=case_number, title="COMPLAINT FOR DAMAGES", causes_list=causes_list, body=body,
        attorney_notes=notes,
    )

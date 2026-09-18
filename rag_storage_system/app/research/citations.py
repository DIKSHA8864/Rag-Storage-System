"""
CITATION ENFORCEMENT IS CODE, NOT PROMPT.

Work Plan Milestone 2: "post-process the answer - extract citation
strings and verify each maps to a retrieved chunk's source file.
Unverifiable citation -> regenerate once with a corrective
instruction; still failing -> return the answer with that citation
stripped and flagged. Log every violation."

This module is the verifier. It knows nothing about Claude and makes
no network calls - it is pure text in, verdict out, which is what lets
Blueprint Tests 1 and 3 run in CI without an API key.

Two independent checks, because they catch different failures:

  1. MARKER CHECK. The prompt requires every sourced statement to carry
     an [S1]-style marker. A marker pointing at a block number that was
     never supplied means the model invented a source slot.

  2. AUTHORITY CHECK - the one that matters. Scan the answer for things
     that LOOK like legal authority (case names, code sections, CACI
     numbers) and require each to appear in the text of a retrieved
     chunk. This is what catches the model reciting a famous case from
     training knowledge, which is Blueprint Test 3 (fabrication probe).
     A marker cannot launder this: citing "[S2]" next to an authority
     that appears nowhere in S2's text still fails.

Deliberately conservative on what counts as authority. A false
positive here strips a legitimate phrase from the answer; a false
negative lets a fabricated citation through. The rules below are
narrow patterns, not a general legal-citation parser.
"""

import re
from dataclasses import dataclass, field

# [S1], [S12], [s3] - the marker form the system prompt mandates.
_MARKER_PATTERN = re.compile(r"\[\s*[Ss](\d{1,3})\s*\]")

# What counts as a legal authority claim. Each pattern is anchored on
# a form that does not occur in ordinary prose.
_AUTHORITY_PATTERNS = [
    # "Smith v. Acme Corp." / "Yanowitz v. L'Oreal USA, Inc."
    re.compile(r"\b[A-Z][A-Za-z'’\-\.]+(?:\s+[A-Z][A-Za-z'’\-\.]+)*\s+v\.?\s+"
               r"[A-Z][A-Za-z'’\-\.]+(?:\s+[A-Za-z'’\-\.,]+)*"),
    # "Labor Code section 1102.5", "Gov. Code § 12940(a)", "§ 226.7"
    re.compile(r"(?:(?:Labor|Government|Gov\.|Civil|Civ\.|Business|Bus\.|"
               r"Penal|Pen\.)\s*(?:&\s*Professions\s*)?Code[,]?\s*)?"
               r"(?:§{1,2}|[Ss]ection[s]?)\s*\d+[\w\.\(\)\-]*"),
    # "29 U.S.C. 201", "2 Cal.App.5th 1", "8 C.C.R. 11040"
    re.compile(r"\b\d+\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?|C\.?C\.?R\.?|"
               r"Cal\.\s?(?:App\.)?\s?\d?\w*|F\.\d d|F\.Supp\.\d?d?)"
               r"\s*\d*[\w\.]*", re.IGNORECASE),
    # "CACI No. 2505", "CACI 2430"
    re.compile(r"\bCACI\s*(?:No\.?\s*)?\d+\b", re.IGNORECASE),
]

# Phrases the model is REQUIRED to produce and which trip the section
# pattern; never treat these as citations.
_ALLOWED_PHRASES = (
    "no authority on this point in the library",
)


@dataclass
class CitationCheck:
    """One verification pass over one candidate answer."""

    invalid_markers: list[int] = field(default_factory=list)
    unsupported_authorities: list[str] = field(default_factory=list)
    verified_authorities: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.invalid_markers and not self.unsupported_authorities

    def as_dict(self) -> dict:
        return {
            "invalid_markers": self.invalid_markers,
            "unsupported_authorities": self.unsupported_authorities,
            "verified_authorities": self.verified_authorities,
        }

    def corrective_instruction(self) -> str:
        """
        The single corrective retry the Work Plan allows, phrased as a
        concrete list of what to remove rather than a repeat of the
        rules (repeating rules the model already broke rarely helps).
        """

        problems = []

        if self.unsupported_authorities:
            listed = "; ".join(sorted(set(self.unsupported_authorities)))
            problems.append(
                f"These authorities do not appear in any provided source and "
                f"must be removed entirely: {listed}."
            )

        if self.invalid_markers:
            listed = ", ".join(f"[S{n}]" for n in sorted(set(self.invalid_markers)))
            problems.append(
                f"These source markers do not exist: {listed}. Use only the "
                f"markers of the sources actually provided."
            )

        return (
            "Your previous answer violated the citation lock. "
            + " ".join(problems)
            + " Rewrite the answer using only the provided sources. If removing "
              "them leaves the point unsupported, answer exactly: "
              '"No authority on this point in the library."'
        )


def _normalize(text: str) -> str:
    """
    Fold the variations that make two spellings of the same citation
    look different: whitespace, section-symbol style, curly quotes.
    """

    text = text.replace("§§", "§").replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\bsections?\b", "§", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower().rstrip(".,;:")


def extract_markers(answer: str) -> list[int]:
    """Every [Sn] marker in the answer, as integers, in order."""

    return [int(match) for match in _MARKER_PATTERN.findall(answer)]


def extract_authorities(answer: str) -> list[str]:
    """
    Every substring of `answer` that looks like a claim of legal
    authority. Overlapping matches are collapsed to the longest.
    """

    spans: list[tuple[int, int, str]] = []

    for pattern in _AUTHORITY_PATTERNS:
        for match in pattern.finditer(answer):
            value = match.group(0).strip()
            if _normalize(value) in (_normalize(p) for p in _ALLOWED_PHRASES):
                continue
            if len(value) < 4:
                continue
            spans.append((match.start(), match.end(), value))

    spans.sort(key=lambda span: (span[0], -(span[1])))

    kept: list[str] = []
    last_end = -1

    for start, end, value in spans:
        if start >= last_end:
            kept.append(value)
            last_end = end

    return kept


def verify_answer(answer: str, sources: list[dict]) -> CitationCheck:
    """
    Verify `answer` against the chunks actually retrieved for it.

    `sources` is the retrieval result list app/retrieval/retriever.py
    returns - each needs at least "chunk_text". Source N in the prompt
    is sources[N - 1]; markers are 1-based because that is how they are
    numbered for the model.
    """

    check = CitationCheck()

    corpus = _normalize(" \n ".join(source.get("chunk_text", "") for source in sources))

    for marker in extract_markers(answer):
        if marker < 1 or marker > len(sources):
            check.invalid_markers.append(marker)

    for authority in extract_authorities(answer):
        if _normalize(authority) in corpus:
            check.verified_authorities.append(authority)
        else:
            check.unsupported_authorities.append(authority)

    return check


def strip_unsupported(answer: str, check: CitationCheck) -> str:
    """
    Last resort after the one allowed regeneration: remove every
    unverifiable citation from the answer and mark the removal
    visibly, so a reader sees that something was taken out rather than
    reading a silently edited answer.

    The Work Plan's wording is "return the answer with that citation
    stripped and flagged" - flagged means visible to the human, which
    is what this bracket does, plus citation_status='stripped' on the
    stored message and the ask_query_logs row.
    """

    cleaned = answer

    for authority in sorted(set(check.unsupported_authorities), key=len, reverse=True):
        cleaned = cleaned.replace(authority, "[citation removed - not in library]")

    for marker in sorted(set(check.invalid_markers)):
        cleaned = re.sub(rf"\[\s*[Ss]{marker}\s*\]", "", cleaned)

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    return cleaned.strip()
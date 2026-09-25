"""
The Blueprint's citation lock, enforced in code (Work Plan M2: "Citation
enforcement is code, not just prompt").

Anything Claude writes for a report or a draft pleading is checked here
before it reaches a document. A legal citation - a statute section, a
case name, a CACI instruction, a regulation - survives only if the same
citation appears in a library passage that was actually given to the
model. Anything else is removed and replaced with a visible marker, and
the removal is returned so the caller can log it. The model can reason
freely; it cannot bring in law the library doesn't contain.
"""

import re

REMOVED_MARKER = "[citation removed - not in the firm's library]"

# Statutes: "Lab. Code § 1102.5", "Labor Code section 98.6(a)", "Gov. Code §12940(h)", "§ 510".
_STATUTE = re.compile(
    r"(?:(?:Cal(?:ifornia)?\.?\s+)?"
    r"(?:Lab(?:or)?\.?|Gov(?:ernment|t)?\.?|Bus(?:iness)?\.?\s*&\s*Prof(?:essions)?\.?|Civ(?:il)?\.?|"
    r"Code\s+Civ\.?\s+Proc\.?|Health\s*&\s*Saf(?:ety)?\.?|Unemp\.?\s+Ins\.?|Evid(?:ence)?\.?|Penal)"
    r"\s*Code,?\s*)?(?:§§?|[Ss]ec(?:tion)?s?\.?)\s*\d+(?:\.\d+)*(?:\s*\([a-z0-9]{1,3}\))*",
)
# Federal: "42 U.S.C. § 2000e", "29 C.F.R. § 541.100", "Cal. Code Regs., tit. 2, § 11068".
_FEDERAL = re.compile(r"\d+\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\s*§*\s*\d+[\w.\-()]*")
_REGS = re.compile(r"Cal\.?\s+Code\s+Regs\.?,?\s+tit\.?\s*\d+,?\s*§\s*\d+[\w.\-()]*")
# Cases: "Yanowitz v. L'Oreal USA, Inc.", "Smith v. Jones".
_CASE = re.compile(
    r"\b(?:[A-Z][A-Za-z'&.\-]*\s){0,4}[A-Z][A-Za-z'&.\-]*\s+v\.\s+(?:[A-Z][A-Za-z'&.\-,]*\s?){1,6}"
)
_CACI = re.compile(r"CACI\s+No\.?\s*\d+[A-Z]?")
_PATTERNS = (_REGS, _FEDERAL, _CACI, _STATUTE, _CASE)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9§]", "", text.lower().replace("section", "§").replace("sec.", "§"))


def find_legal_citations(text: str) -> list[str]:
    found: list[tuple[int, int, str]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            span = (match.start(), match.end())
            if any(start <= span[0] < end or start < span[1] <= end for start, end, _ in found):
                continue  # already covered by a more specific pattern
            found.append((span[0], span[1], match.group(0).strip().rstrip(",.;")))
    return [citation for _, _, citation in sorted(found)]


def _grounded(citation: str, library_text: str) -> bool:
    normalized = _normalize(citation)
    if normalized and normalized in library_text:
        return True
    # A statute is grounded by its section number appearing as a section in the passages
    # ("§ 1102.5" in the library grounds "Labor Code section 1102.5").
    section = re.search(r"(?:§§?|[Ss]ec(?:tion)?s?\.?)\s*(\d+(?:\.\d+)*)", citation)
    if section and f"§{section.group(1).replace('.', '')}" in library_text:
        return True
    # A case is grounded when both party names appear together in one normalized run of the library.
    if " v. " in citation:
        plaintiff, defendant = citation.split(" v. ", 1)
        first = _normalize(plaintiff.split()[-1]) if plaintiff.split() else ""
        second = _normalize(defendant.split()[0]) if defendant.split() else ""
        if first and second and f"{first}v{second}" in library_text:
            return True
    return False


def library_index(passage_texts: list[str], allowed: tuple[str, ...] = ()) -> str:
    """
    Normalized library text the citations are checked against (build once
    per request). `allowed` adds names that are not legal authority but may
    look like it - e.g. the case's own caption "Lopez v. Harbor Grill".
    """

    return "|".join(_normalize(text) for text in [*passage_texts, *allowed])


def grounded_in(citation: str, passage_text: str) -> bool:
    """Whether `citation` really appears in this one passage."""

    return bool(find_legal_citations(citation)) and _grounded(citation, library_index([passage_text]))


def enforce(text: str, library: str) -> tuple[str, list[str]]:
    """(text with every ungrounded citation replaced by REMOVED_MARKER, the citations removed)."""

    removed = []
    for citation in find_legal_citations(text):
        if not _grounded(citation, library):
            removed.append(citation)
            text = text.replace(citation, REMOVED_MARKER)
    return text, removed

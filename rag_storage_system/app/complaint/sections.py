"""Flattens a ComplaintDraft into (heading, paragraphs) pairs - same pattern as app/report/sections.py. Cited Legal Authority and Research Suggestions are always separate sections, never merged."""

from app.complaint.schema import ComplaintDraft


def complaint_sections(complaint: ComplaintDraft) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = [
        ("Parties", [
            f"Plaintiff: {complaint.plaintiff_name}",
            f"Defendant: {complaint.defendant_placeholder}",
        ]),
        ("Jurisdiction and Venue", [complaint.jurisdiction_placeholder]),
    ]
    if complaint.drafting_note:
        sections.insert(0, ("How this draft was prepared", [complaint.drafting_note]))
    if complaint.general_allegations:
        sections.append(("General Allegations", [f"- {a}" for a in complaint.general_allegations]))

    for cause in complaint.causes_of_action:
        heading = f"Cause of Action: {cause.name}"
        paragraphs = []
        if cause.allegations:
            paragraphs = [f"- {allegation}" for allegation in cause.allegations]
        else:
            for element in cause.elements:
                if element.satisfied_by:
                    paragraphs.append(f"- {element.description}: {element.satisfied_by}")
                else:
                    paragraphs.append(f"- {element.description}: {element.placeholder}")
        sections.append((heading, paragraphs))

        sections.append((f"{cause.name} - Cited Legal Authority",
                         list(dict.fromkeys([cause.authority_citation, *cause.verified_authorities]))))

        if cause.research_suggestions:
            sections.append((
                f"{cause.name} - Research Suggestions (NOT cited authority - attorney must verify)",
                [f"{r.filename} ({r.category}): {r.chunk_text}" for r in cause.research_suggestions],
            ))

    if complaint.ai_research_suggestions:
        sections.append(("Research Questions (NOT cited authority - attorney must verify)",
                         complaint.ai_research_suggestions))
    sections.append(("Attorney Review Notice", [complaint.attorney_review_notice]))
    sections.append(("Disclaimer", [complaint.disclaimer_text]))

    return sections
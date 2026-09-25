"""
Structured complaint draft schema. Mirrors app/report/schema.py's
rules: no LLM formats the final document, no fabricated authority (an
element's `authority_citation` is copied verbatim from
cause_of_action_library, curated by the Owner/attorney - never
generated), and Research Suggestions are a clearly separate field from
cited legal authority so they can never be rendered as if they were
the same thing.
"""

from pydantic import BaseModel, Field


class ComplaintElement(BaseModel):
    """One legal element of a cause of action, and whether the intake facts satisfy it."""

    description: str
    satisfied_by: str | None = Field(
        default=None, description="The intake fact/document text that supports this element, if one was found."
    )
    placeholder: str | None = Field(
        default=None,
        description="Bracketed placeholder text for attorney completion, set only when no supporting fact was found.",
    )


class ResearchSuggestion(BaseModel):
    """
    A retrieval hit surfaced as background research - NOT cited legal
    authority. Must always be rendered under its own heading, visually
    separate from ComplaintCauseOfAction.authority_citation.
    """

    filename: str
    category: str
    chunk_text: str
    score: float


class ComplaintCauseOfAction(BaseModel):
    cause_of_action_id: int
    name: str
    authority_citation: str = Field(..., description="Curated, library-only - never generated.")
    elements: list[ComplaintElement]
    research_suggestions: list[ResearchSuggestion] = Field(default_factory=list)
    # Written by Claude (app/complaint/claude_drafting.py) when available -
    # otherwise empty and the element list above is pleaded instead.
    allegations: list[str] = Field(default_factory=list)
    # Authority Claude cited, each verified in code against the library passage it came from.
    verified_authorities: list[str] = Field(default_factory=list)


class ComplaintDraft(BaseModel):
    intake_session_id: int
    matter_name: str
    generated_at: str

    plaintiff_name: str
    defendant_placeholder: str = "[DEFENDANT NAME TO BE PROVIDED BY ATTORNEY]"
    jurisdiction_placeholder: str = "[JURISDICTION/VENUE TO BE PROVIDED BY ATTORNEY]"

    causes_of_action: list[ComplaintCauseOfAction]

    # Facts common to every cause of action (employment, timeline) - Claude-drafted when available.
    general_allegations: list[str] = Field(default_factory=list)
    # Questions to research beyond the library - never cited authority.
    ai_research_suggestions: list[str] = Field(default_factory=list)
    drafting_note: str | None = None

    attorney_review_notice: str = (
        "This is a DRAFT pleading assembled from Client intake data and the firm's curated legal-elements "
        "library. It has not been reviewed by an attorney, contains bracketed placeholders that MUST be "
        "completed, and must not be filed or served until an attorney has reviewed it in full."
    )
    disclaimer_text: str
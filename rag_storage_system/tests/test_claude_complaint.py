"""
Complaint allegations drafted by Claude (app/complaint/claude_drafting.py).
Claude is faked, so these run without an API key - what's tested is the
input it gets, the citation checks applied to what it returns, the
fallback, and the pleading built from it.
"""

import pytest

from app.analysis import citation_lock
from app.analysis.structured_claude import ClaudeUnavailable
from app.complaint import claude_drafting
from app.complaint.builder import build_complaint_draft
from app.complaint.pleading import build_pleading_content
from app.complaint.sections import complaint_sections
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from config.settings import get_settings

LIBRARY_CHUNK = {
    "chunk_id": "lib-1", "document_id": "d1", "category": "Wage", "filename": "overtime_rules.docx", "section": "2",
    "chunk_text": "Labor Code § 510 requires overtime pay for work over eight hours in a workday. "
                  "See Martinez v. Combs on who counts as an employer.",
    "final_score": 0.9,
}
CASE_CHUNK = {
    "chunk_id": "case-1", "document_id": "matter-5:case-1", "category": "matter-5", "filename": "demand_letter.txt",
    "chunk_text": "Demand letter citing Gov. Code § 12940(h) and Brinker v. Superior Court.", "final_score": 0.8,
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    from app.complaint import builder

    monkeypatch.setattr(builder, "retrieve_for_matter", lambda *a, **k: [])
    monkeypatch.setattr(claude_drafting, "retrieve_for_matter", lambda *a, **k: [LIBRARY_CHUNK, CASE_CHUNK])
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def draft(repo):
    session = repo.create_intake_session(matter_id=0, title="Intake")
    repo.add_intake_fact(session["id"], "general", "client_story", "I cooked at Harbor Grill 60 hours a week with no overtime.")
    overtime = repo.create_cause_of_action("Wage", "Failure to Pay Overtime",
                                           ["Plaintiff worked overtime", "Overtime was not paid"], "Cal. Lab. Code § 510")
    retaliation = repo.create_cause_of_action("Retaliation", "Retaliation", ["Protected activity"], "Cal. Lab. Code § 98.6")
    return build_complaint_draft(session["id"], 5, "Lopez v. Harbor Grill", [overtime["id"], retaliation["id"]], repo)


@pytest.fixture
def claude(monkeypatch, draft):
    overtime, retaliation = draft.causes_of_action
    calls = []
    reply = {
        "general_allegations": [
            "Plaintiff worked for Defendant Harbor Grill as a cook in Lopez v. Harbor Grill.",
            "Plaintiff began work on [ATTORNEY TO CONFIRM: start date].",
        ],
        "causes_of_action": [
            {"cause_of_action_id": overtime.cause_of_action_id,
             "allegations": ["Plaintiff regularly worked about 60 hours a week.",
                             "Defendant never paid overtime, in violation of Lab. Code § 510 and Lab. Code § 1194."],
             "authorities": [
                 {"citation": "Labor Code § 510", "source_id": "S1"},       # in the library passage
                 {"citation": "Martinez v. Combs", "source_id": "S1"},      # in the library passage
                 {"citation": "Brinker v. Superior Court", "source_id": "S2"},  # case record - never authority
                 {"citation": "Labor Code § 226.7", "source_id": "S1"},     # not in the passage it points to
                 {"citation": "Labor Code § 510", "source_id": "S9"},       # no such passage
             ]},
            {"cause_of_action_id": 999, "allegations": ["Not a selected cause."], "authorities": []},
        ],
        "research_suggestions": ["Whether meal-break premiums are also owed (see Brinker v. Superior Court)."],
    }

    def fake(purpose, model, system, user_content, schema, **kwargs):
        calls.append({"purpose": purpose, "model": model, "system": system, "user": user_content, **kwargs})
        return reply

    monkeypatch.setattr(claude_drafting, "call_claude_json", fake)
    return calls


def test_claude_drafts_allegations_and_only_library_authority_survives(repo, draft, claude):
    claude_drafting.apply_claude_drafting(draft, 5, repo, plaintiff_name="MARIA LOPEZ", defendant_name="HARBOR GRILL, INC.")

    call = claude[0]
    assert call["purpose"] == "complaint_drafting" and call["model"] == get_settings().drafting_model
    assert "60 hours a week" in call["user"] and "Overtime was not paid" in call["user"]
    assert 'defendant="HARBOR GRILL, INC."' in call["user"] and 'origin="case record"' in call["user"]

    overtime, retaliation = draft.causes_of_action
    assert overtime.verified_authorities == [
        "Labor Code § 510 (library: overtime_rules.docx, section 2)",
        "Martinez v. Combs (library: overtime_rules.docx, section 2)",
    ]
    assert overtime.allegations[0] == "Plaintiff regularly worked about 60 hours a week."
    assert "Lab. Code § 510" in overtime.allegations[1]                      # the library has § 510
    assert "§ 1194" not in overtime.allegations[1] and citation_lock.REMOVED_MARKER in overtime.allegations[1]
    assert retaliation.allegations == [] and retaliation.verified_authorities == []
    assert draft.general_allegations[0].endswith("in Lopez v. Harbor Grill.")  # the case's own caption is kept
    assert "Brinker" not in draft.ai_research_suggestions[0]
    assert "written by Claude" in draft.drafting_note
    assert "citation(s) not found in the firm's library were removed" in draft.drafting_note
    assert "No allegations were drafted for: Retaliation" in draft.drafting_note

    content = build_pleading_content(draft, None, plaintiff="MARIA LOPEZ", defendant="HARBOR GRILL, INC.")
    blocks = [(b.kind, b.text) for b in content.body]
    general = blocks.index(("heading", "GENERAL ALLEGATIONS"))
    assert blocks[general + 1] == ("numbered", draft.general_allegations[0])
    numbered = [text for kind, text in blocks if kind == "numbered"]
    assert "Plaintiff regularly worked about 60 hours a week." in numbered
    assert ("Authority: Cal. Lab. Code § 510; Labor Code § 510 (library: overtime_rules.docx, section 2); "
            "Martinez v. Combs (library: overtime_rules.docx, section 2)") in numbered
    assert any(text.startswith("Protected activity:") for text in numbered)  # Retaliation falls back to elements
    assert "Not a selected cause." not in numbered
    notes = dict(content.attorney_notes)
    assert notes["How this draft was prepared"] == [draft.drafting_note]
    assert notes["Research questions (NOT cited authority - attorney must verify)"] == draft.ai_research_suggestions

    preview = dict(complaint_sections(draft))
    assert preview["General Allegations"][0].startswith("- Plaintiff worked for Defendant")
    assert "Research Questions (NOT cited authority - attorney must verify)" in preview


def test_owner_edited_prompt_is_used(repo, draft, claude):
    repo.create_prompt_version(claude_drafting.PROMPT_NAME, "OWNER DRAFTING PROMPT", "owner@example.com")

    claude_drafting.apply_claude_drafting(draft, 5, repo)

    assert claude[0]["system"] == "OWNER DRAFTING PROMPT"


def test_without_claude_the_element_draft_stands_and_says_so(repo, draft, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ClaudeUnavailable("The Claude call failed: credit balance is too low")

    monkeypatch.setattr(claude_drafting, "call_claude_json", unavailable)

    claude_drafting.apply_claude_drafting(draft, 5, repo)

    assert draft.drafting_note.startswith("Drafting method: template")
    assert "credit balance is too low" in draft.drafting_note
    assert all(not c.allegations and not c.verified_authorities for c in draft.causes_of_action)
    numbered = [b.text for b in build_pleading_content(draft, None).body if b.kind == "numbered"]
    assert any(text.startswith("Plaintiff worked overtime:") for text in numbered)
    assert "GENERAL ALLEGATIONS" not in [b.text for b in build_pleading_content(draft, None).body]


def test_no_api_key_means_no_retrieval_and_no_call(repo, draft, claude, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    monkeypatch.setattr(claude_drafting, "retrieve_for_matter", lambda *a, **k: pytest.fail("retrieval ran"))

    claude_drafting.apply_claude_drafting(draft, 5, repo)

    assert claude == [] and "ANTHROPIC_API_KEY is not set" in draft.drafting_note


def test_nothing_recorded_means_no_call(repo, claude):
    empty = repo.create_intake_session(matter_id=0, title="Empty")
    cause = repo.create_cause_of_action("Wage", "Overtime", ["Worked overtime"], "Cal. Lab. Code § 510")
    draft = build_complaint_draft(empty["id"], 5, "Case", [cause["id"]], repo)

    claude_drafting.apply_claude_drafting(draft, 5, repo)

    assert claude == [] and "nothing has been recorded" in draft.drafting_note

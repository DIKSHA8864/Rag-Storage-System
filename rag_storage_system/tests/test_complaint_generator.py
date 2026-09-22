"""Tests for the Complaint Generator (app/complaint/) - curated elements/authority, bracketed placeholders for missing facts, and Research Suggestions kept visually separate from cited authority."""

import pytest

from app.complaint.builder import build_complaint_draft
from app.metadata.sqlite_repository import SQLiteMetadataRepository


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


def test_satisfied_element_uses_the_matching_intake_fact(monkeypatch, repo):
    from app.complaint import builder as builder_module

    monkeypatch.setattr(builder_module, "retrieve_for_matter", lambda *a, **k: [])

    session = repo.create_intake_session(matter_id=1, title="Intake")
    repo.add_intake_fact(session["id"], "mandatory_sweep", "overtime", "I worked 50 hours a week without overtime pay.")
    cause = repo.create_cause_of_action(
        "Wage & Hour", "Failure to Pay Overtime", ["Employee worked overtime hours without overtime pay"], "Labor Code Section 510"
    )

    draft = build_complaint_draft(session["id"], 1, "Acme Corp", [cause["id"]], repo)

    element = draft.causes_of_action[0].elements[0]
    assert element.satisfied_by is not None
    assert "overtime" in element.satisfied_by
    assert element.placeholder is None
    assert draft.causes_of_action[0].authority_citation == "Labor Code Section 510"


def test_missing_fact_becomes_a_bracketed_placeholder(monkeypatch, repo):
    from app.complaint import builder as builder_module

    monkeypatch.setattr(builder_module, "retrieve_for_matter", lambda *a, **k: [])

    session = repo.create_intake_session(matter_id=1, title="Intake")
    cause = repo.create_cause_of_action(
        "Retaliation", "Whistleblower Retaliation", ["Employee suffered an adverse employment action after protected activity"], "Labor Code Section 1102.5"
    )

    draft = build_complaint_draft(session["id"], 1, "Acme Corp", [cause["id"]], repo)

    element = draft.causes_of_action[0].elements[0]
    assert element.satisfied_by is None
    assert element.placeholder.startswith("[ATTORNEY TO PROVIDE:")


def test_research_suggestions_are_a_separate_field_from_cited_authority(monkeypatch, repo):
    from app.complaint import builder as builder_module

    monkeypatch.setattr(
        builder_module, "retrieve_for_matter",
        lambda *a, **k: [{"filename": "wage_policy.pdf", "category": "Wage & Hour", "chunk_text": "policy text", "final_score": 0.8}],
    )

    session = repo.create_intake_session(matter_id=1, title="Intake")
    cause = repo.create_cause_of_action("Wage & Hour", "Failure to Pay Overtime", ["Employee worked overtime"], "Labor Code Section 510")

    draft = build_complaint_draft(session["id"], 1, "Acme Corp", [cause["id"]], repo)

    result_cause = draft.causes_of_action[0]
    assert result_cause.authority_citation == "Labor Code Section 510"
    assert len(result_cause.research_suggestions) == 1
    assert result_cause.research_suggestions[0].filename == "wage_policy.pdf"
    # The two are never the same field/value - authority is fixed, research is exploratory.
    assert result_cause.research_suggestions[0].chunk_text != result_cause.authority_citation
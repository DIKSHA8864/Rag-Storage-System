"""
The intake report's Claude-written analysis (app/report/claude_analysis.py):
Claude is faked here, so these run without an API key - what's tested is
everything around the model: the inputs it gets, the citation lock applied
to what it returns, the fallback, and the rendered report.
"""

import pytest

from app.analysis import citation_lock
from app.analysis.structured_claude import ClaudeUnavailable
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.report import claude_analysis, rag_analysis
from app.report.builder import build_structured_report
from app.report.sections import report_sections
from config.settings import get_settings

LIBRARY_CHUNK = {
    "chunk_id": "lib-1", "document_id": "d1", "category": "Wage", "filename": "overtime_rules.docx", "section": "2",
    "chunk_text": "Labor Code § 510 requires overtime pay for work over eight hours in a workday.", "final_score": 0.9,
}
CASE_CHUNK = {
    "chunk_id": "case-1", "document_id": "matter-5:case-1", "category": "matter-5", "filename": "order.txt",
    "chunk_text": "ORDER: demurrer overruled as to the overtime claim.", "final_score": 0.8,
}


@pytest.fixture
def repo(tmp_path):
    repo = SQLiteMetadataRepository(tmp_path / "metadata.db")
    return repo


@pytest.fixture
def session(repo, monkeypatch):
    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k, tenant_id=1: [LIBRARY_CHUNK, CASE_CHUNK])
    s = repo.create_intake_session(matter_id=0, title="Intake")
    repo.add_intake_fact(s["id"], "general", "client_story", "I worked 60 hours a week at Harbor Grill and got no overtime.")
    repo.add_intake_fact(s["id"], "mandatory_sweep", "overtime", "Yes - about 20 hours a week, never paid.")
    return s


@pytest.fixture
def claude(monkeypatch):
    calls = []
    reply = {
        "fact_summary": "The client worked about 60 hours a week at Harbor Grill without overtime pay "
                        "(see Lab. Code § 510; also Gov. Code § 12940(h)).",
        "causes_of_action": [
            {"name": "Failure to pay overtime", "supporting_facts": ["60-hour weeks", "no overtime paid"],
             "source_ids": ["S1", "S2", "S9"]},
            {"name": "Retaliation", "supporting_facts": ["complained to HR"], "source_ids": []},
        ],
        "strengths": [{"text": "Consistent account of hours", "source_ids": ["S1"]}],
        "weaknesses": [{"text": "No time records yet (Smith v. Jones)", "source_ids": []}],
        "missing_information": ["Pay stubs for 2022-2023"],
        "research_suggestions": ["Whether the flat daily rate was lawful under Smith v. Jones"],
    }

    def fake(purpose, model, system, user_content, schema, **kwargs):
        calls.append({"purpose": purpose, "model": model, "system": system, "user": user_content, "schema": schema})
        return reply

    monkeypatch.setattr(claude_analysis, "call_claude_json", fake)
    return calls


def _texts(report):
    return "\n".join(line for heading, paragraphs in report_sections(report) for line in [heading, *paragraphs])


def test_claude_writes_the_analysis_and_the_citation_lock_holds(repo, session, claude):
    report = build_structured_report(session["id"], "Lopez v. Harbor Grill", repo)

    call = claude[0]
    assert call["purpose"] == "intake_report_analysis"
    assert call["model"] == get_settings().drafting_model
    assert "overtime_rules.docx" in call["user"] and 'origin="case record"' in call["user"]
    assert "I worked 60 hours a week" in call["user"]

    assert "Lab. Code § 510" in report.summary  # in the library passage
    assert "Gov. Code § 12940(h)" not in report.summary and citation_lock.REMOVED_MARKER in report.summary
    overtime, retaliation = report.potential_causes_of_action
    assert "Library authority: overtime_rules.docx (section 2)" in overtime
    assert "order.txt" not in overtime  # a case-record passage is never legal authority
    assert retaliation.endswith(claude_analysis.NO_AUTHORITY)
    assert report.strengths == ["Consistent account of hours [Library: overtime_rules.docx (section 2)]"]
    assert "Smith v. Jones" not in " ".join(report.weaknesses + report.research_suggestions)
    assert [c.filename for c in report.citations] == ["overtime_rules.docx"]
    assert "written by Claude" in report.analysis_note and "citation(s) not found in the library were removed" in report.analysis_note

    text = _texts(report)
    assert "Research Suggestions (NOT cited authority - attorney must verify)" in text
    assert "Pay stubs for 2022-2023" in text


def test_owner_edited_prompt_is_used(repo, session, claude):
    repo.create_prompt_version(claude_analysis.PROMPT_NAME, "OWNER PROMPT: be brief.", "owner@example.com")

    build_structured_report(session["id"], "Intake", repo)

    assert claude[0]["system"] == "OWNER PROMPT: be brief."


def test_without_claude_the_template_analysis_stands_and_says_so(repo, session, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ClaudeUnavailable("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(claude_analysis, "call_claude_json", unavailable)

    report = build_structured_report(session["id"], "Intake", repo)

    assert report.analysis_note.startswith("Analysis method: template")
    assert "ANTHROPIC_API_KEY is not set" in report.analysis_note
    assert report.research_suggestions == []
    assert report.citations  # the template's library matches are still there


def test_nothing_recorded_means_no_model_call(repo, claude):
    empty = repo.create_intake_session(matter_id=0, title="Empty")

    report = build_structured_report(empty["id"], "Intake", repo)

    assert claude == []
    assert "template" in report.analysis_note


def test_no_scores_in_the_schema():
    fields = set(claude_analysis.OUTPUT_SCHEMA["properties"])
    assert not {f for f in fields if any(word in f for word in ("score", "rating", "likelihood", "probability"))}

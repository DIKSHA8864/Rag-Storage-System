"""
Tests for the RAG-backed report grounding (app/report/rag_analysis.py) -
retrieval per fact, library-only citations, and the deterministic
potential-causes-of-action/strengths/weaknesses/missing-information
sections it feeds into app/report/builder.py's StructuredReport.
"""

import io

import pytest
from docx import Document

from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.report import rag_analysis
from app.report.builder import build_structured_report
from app.report.docx_renderer import DocxReportRenderer
from app.report.rag_analysis import FactSupport, build_rag_sections, gather_fact_support


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


def _hit(filename: str, category: str, score: float) -> dict:
    return {
        "chunk_id": "c-1", "document_id": "doc", "category": category, "filename": filename,
        "chunk_text": "policy text", "section": "1.1", "start_page": 1, "end_page": 1,
        "final_score": score,
    }


def test_well_supported_fact_is_classified_as_match_with_a_library_only_citation(monkeypatch, repo):
    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [_hit("policy.pdf", "HR", 0.9)])

    results = gather_fact_support(["I was fired after reporting a safety issue."], repo)

    assert len(results) == 1
    assert results[0].classification == "match"
    assert results[0].citations == [
        {"filename": "policy.pdf", "category": "HR", "section": "1.1", "start_page": 1, "end_page": 1, "score": 0.9}
    ]


def test_weakly_supported_fact_is_classified_as_partial_match(monkeypatch, repo):
    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [_hit("policy.pdf", "HR", 0.35)])

    results = gather_fact_support(["Some vague fact."], repo)

    assert results[0].classification == "partial_match"


def test_fact_with_no_hits_is_classified_as_gap(monkeypatch, repo):
    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [])

    results = gather_fact_support(["Totally unrelated fact."], repo)

    assert results[0].classification == "gap"
    assert results[0].citations == []


def test_retrieval_failure_degrades_to_unavailable_instead_of_raising(monkeypatch, repo):
    def _boom(query, top_k):
        raise ConnectionError("no pgvector reachable")

    monkeypatch.setattr(rag_analysis, "retrieve", _boom)

    results = gather_fact_support(["Any fact."], repo)

    assert results[0].classification == "unavailable"
    assert results[0].citations == []


def test_citations_never_include_a_filename_outside_the_retrieved_set(monkeypatch, repo):
    """Library-only citations: every citation traces to exactly what retrieve() returned - nothing invented."""

    monkeypatch.setattr(
        rag_analysis, "retrieve",
        lambda query, top_k: [_hit("a.pdf", "HR", 0.9), _hit("b.pdf", "Safety", 0.9)],
    )

    results = gather_fact_support(["fact one"], repo)

    cited_filenames = {c["filename"] for c in results[0].citations}
    assert cited_filenames == {"a.pdf", "b.pdf"}


def test_build_rag_sections_populates_strengths_weaknesses_missing_and_causes():
    fact_supports = [
        FactSupport(fact_text="strong fact", classification="match",
                    citations=[{"filename": "a.pdf", "category": "HR", "section": None, "start_page": None, "end_page": None, "score": 0.9}]),
        FactSupport(fact_text="weak fact", classification="partial_match", citations=[]),
        FactSupport(fact_text="unrelated fact", classification="gap", citations=[]),
        FactSupport(fact_text="unchecked fact", classification="unavailable", citations=[]),
    ]

    sections = build_rag_sections(fact_supports)

    assert sections["supporting_facts"] == ["strong fact", "weak fact", "unrelated fact", "unchecked fact"]
    assert len(sections["strengths"]) == 1 and "strong fact" in sections["strengths"][0]
    assert len(sections["weaknesses"]) == 1 and "weak fact" in sections["weaknesses"][0]
    assert any("unrelated fact" in m for m in sections["missing_information"])
    assert any("unchecked fact" in m for m in sections["missing_information"])
    assert len(sections["potential_causes_of_action"]) == 1
    assert "HR" in sections["potential_causes_of_action"][0]


def test_potential_causes_of_action_are_deduplicated_by_category():
    fact_supports = [
        FactSupport(fact_text="fact 1", classification="match",
                    citations=[{"filename": "a.pdf", "category": "HR", "section": None, "start_page": None, "end_page": None, "score": 0.9}]),
        FactSupport(fact_text="fact 2", classification="match",
                    citations=[{"filename": "b.pdf", "category": "HR", "section": None, "start_page": None, "end_page": None, "score": 0.8}]),
    ]

    sections = build_rag_sections(fact_supports)

    assert len(sections["potential_causes_of_action"]) == 1


def test_build_structured_report_includes_rag_backed_sections(monkeypatch, repo):
    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [_hit("policy.pdf", "HR", 0.9)])

    session = repo.create_intake_session(matter_id=0, title="Intake")
    uploaded_input = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=0, original_filename="notes.txt", stored_category="session_1",
        stored_filename="notes.txt", media_type="document", size=10, sha256=None,
    )
    repo.add_extracted_information(uploaded_input["id"], "text", "I was fired after reporting a safety issue.", "document_extractor", False)

    report = build_structured_report(session["id"], "Acme Corp", repo)

    assert report.supporting_facts == ["I was fired after reporting a safety issue."]
    assert len(report.strengths) == 1
    assert len(report.citations) == 1
    assert report.citations[0].filename == "policy.pdf"
    assert len(report.potential_causes_of_action) == 1


def test_docx_report_renders_the_rag_backed_sections(monkeypatch, repo):
    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [_hit("policy.pdf", "HR", 0.9)])

    session = repo.create_intake_session(matter_id=0, title="Intake")
    uploaded_input = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=0, original_filename="notes.txt", stored_category="session_1",
        stored_filename="notes.txt", media_type="document", size=10, sha256=None,
    )
    repo.add_extracted_information(uploaded_input["id"], "text", "I was fired after reporting a safety issue.", "document_extractor", False)

    report = build_structured_report(session["id"], "Acme Corp", repo)
    content = DocxReportRenderer().render(report)

    document = Document(io.BytesIO(content))
    full_text = "\n".join(p.text for p in document.paragraphs)

    assert "Potential Causes of Action" in full_text
    assert "policy.pdf" in full_text
    assert "Strengths" in full_text
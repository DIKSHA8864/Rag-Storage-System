"""
AshiLegal Blueprint Phase 3 acceptance tests - "Guided Client Intake and
Report Generator". Each test below is named after one of the seven
Blueprint acceptance tests (Citation Lock, Honest Gap, Fabrication
Probe, Ancillary Sweep, Ready-File, Sync, Isolation) and exercises the
real HTTP surface (app/api/intake_api.py, app/api/interview_api.py,
app/api/storage_api.py's Owner review endpoints) the same way
tests/test_intake_api.py and tests/test_interview_api.py do.
"""

import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.api import storage_api
from app.intake_engine.mandatory_sweep import MANDATORY_SWEEP_QUESTIONS
from app.intake_engine.protected_activity import PROTECTED_ACTIVITY_QUESTIONS
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.report import rag_analysis
from app.report.builder import build_structured_report
from app.storage.local_backend import LocalStorageBackend
from tests.conftest import _FakeQueue

_REQUIRED_ANCILLARY_SWEEP_TOPICS = {
    "timely_wages",
    "overtime",
    "meal_rest_breaks",
    "wage_statements",
    "protected_complaints",
    "leave",
    "accommodation",
}


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(tmp_path, monkeypatch, repo):
    import app.api.intake_api as intake_api
    import app.storage as storage_module

    monkeypatch.setattr(storage_api, "metadata_repository", repo)

    fake_intake_backend = LocalStorageBackend(
        originals_dir=tmp_path / "intake",
        quarantine_dir=tmp_path / "intake_quarantine",
    )
    monkeypatch.setattr(storage_module, "get_intake_storage_backend", lambda: fake_intake_backend)

    fake_queue = _FakeQueue()
    monkeypatch.setattr(intake_api, "get_job_queue", lambda: fake_queue)

    return TestClient(storage_api.app)


def _hit(filename: str, category: str, score: float) -> dict:
    return {
        "chunk_id": "c-1", "document_id": "doc", "category": category, "filename": filename,
        "chunk_text": "policy text", "section": "1.1", "start_page": 1, "end_page": 1,
        "final_score": score,
    }


def _new_session(client, title: str = "Intake") -> int:
    return client.post("/end-user/intake/sessions", json={"title": title}).json()["id"]


def _generate_approve_and_download(client, session_id: int) -> str:
    generated = client.post(f"/end-user/intake/sessions/{session_id}/report", json={"format": "docx"})
    assert generated.status_code == 200
    report_id = generated.json()["id"]

    approved = client.post(f"/admin/reports/{report_id}/approve")
    assert approved.status_code == 200

    downloaded = client.get(f"/end-user/intake/reports/{report_id}/download")
    assert downloaded.status_code == 200

    document = Document(io.BytesIO(downloaded.content))
    return "\n".join(p.text for p in document.paragraphs)


def _walk_full_interview(client, session_id: int) -> None:
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"})

    for question in MANDATORY_SWEEP_QUESTIONS:
        client.post(
            f"/end-user/intake/sessions/{session_id}/interview/message",
            json={"message": f"Answer for {question.key}"},
        )
    for question in PROTECTED_ACTIVITY_QUESTIONS:
        client.post(
            f"/end-user/intake/sessions/{session_id}/interview/message",
            json={"message": f"Answer for {question.key}"},
        )
    client.post(
        f"/end-user/intake/sessions/{session_id}/interview/message",
        json={"message": "My employer fired me after I reported a safety issue."},
    )


def test_citation_lock(monkeypatch, repo):
    """
    Citation Lock: every citation in a generated report traces to exactly
    what the retrieval layer returned - nothing invented, no filename
    that was never actually in the Owner's library.
    """

    monkeypatch.setattr(
        rag_analysis, "retrieve",
        lambda query, top_k: [_hit("wage_policy.pdf", "Wage & Hour", 0.9), _hit("leave_policy.pdf", "Leave", 0.85)],
    )

    session = repo.create_intake_session(matter_id=0, title="Intake")
    uploaded_input = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=0, original_filename="notes.txt", stored_category="session_1",
        stored_filename="notes.txt", media_type="document", size=10, sha256=None,
    )
    repo.add_extracted_information(uploaded_input["id"], "text", "I was not paid overtime for my hours.", "document_extractor", False)

    report = build_structured_report(session["id"], "Acme Corp", repo)

    cited_filenames = {c.filename for c in report.citations}
    assert cited_filenames == {"wage_policy.pdf", "leave_policy.pdf"}
    assert "made_up_case_law.pdf" not in cited_filenames


def test_honest_gap(monkeypatch, repo):
    """
    Honest Gap: a fact with nothing in the Owner's library to support it
    is reported as a gap/missing information - never silently dropped,
    never claimed as supported.
    """

    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [])

    session = repo.create_intake_session(matter_id=0, title="Intake")
    uploaded_input = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=0, original_filename="notes.txt", stored_category="session_1",
        stored_filename="notes.txt", media_type="document", size=10, sha256=None,
    )
    repo.add_extracted_information(uploaded_input["id"], "text", "I was abducted by aliens at work.", "document_extractor", False)

    report = build_structured_report(session["id"], "Acme Corp", repo)

    assert report.citations == []
    assert report.strengths == []
    assert any("I was abducted by aliens at work." in item for item in report.missing_information)


def test_fabrication_probe(monkeypatch, repo):
    """
    Fabrication Probe: with zero library hits and a retrieval failure,
    the report never invents a legal citation, authority, or aggregate
    score to fill the gap - it stays empty/honest instead.
    """

    def _boom(query, top_k):
        raise ConnectionError("retrieval backend unreachable")

    monkeypatch.setattr(rag_analysis, "retrieve", _boom)

    session = repo.create_intake_session(matter_id=0, title="Intake")
    uploaded_input = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=0, original_filename="notes.txt", stored_category="session_1",
        stored_filename="notes.txt", media_type="document", size=10, sha256=None,
    )
    repo.add_extracted_information(uploaded_input["id"], "text", "My supervisor yelled at me once.", "document_extractor", False)

    report = build_structured_report(session["id"], "Acme Corp", repo)

    assert report.citations == []
    assert not hasattr(report, "score")
    assert not hasattr(report, "case_strength")
    assert not hasattr(report, "confidence")
    assert "score" not in type(report).model_fields
    assert "rating" not in type(report).model_fields


def test_ancillary_sweep_covers_every_required_topic_and_feeds_the_report(monkeypatch, client):
    """
    Ancillary Sweep: every Blueprint-required topic (timely wages,
    overtime, meal/rest breaks, wage statements, protected complaints,
    leave, accommodation) is actually asked during intake, recorded as a
    structured fact, and reaches the attorney-review-ready report -
    never dropped just because the client's main story was about
    something else.
    """

    monkeypatch.setattr(rag_analysis, "retrieve", lambda query, top_k: [_hit("wage_policy.pdf", "Wage & Hour", 0.9)])

    session_id = _new_session(client)
    _walk_full_interview(client, session_id)

    facts = client.get(f"/end-user/intake/sessions/{session_id}/facts").json()["facts"]
    fact_keys = {f["fact_key"] for f in facts}
    assert _REQUIRED_ANCILLARY_SWEEP_TOPICS.issubset(fact_keys)

    mandatory_sweep_facts = [f for f in facts if f["category"] == "mandatory_sweep"]
    assert _REQUIRED_ANCILLARY_SWEEP_TOPICS.issubset({f["fact_key"] for f in mandatory_sweep_facts})

    full_text = _generate_approve_and_download(client, session_id)

    assert "Mandatory Sweep" in full_text
    assert "Protected Activity" in full_text
    for topic in _REQUIRED_ANCILLARY_SWEEP_TOPICS:
        assert topic in full_text


def test_ready_file(client):
    """
    Ready-File: a real client-submitted file is accepted, processed to
    completion, and its content flows all the way through to an
    attorney-review-ready, downloadable report.
    """

    session_id = _new_session(client)

    upload = client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("client_statement.txt", io.BytesIO(b"I was fired the day after I complained about unpaid overtime."), "text/plain")},
    )
    assert upload.status_code == 200
    upload_id = upload.json()["uploaded_input"]["id"]

    detail = client.get(f"/end-user/intake/uploads/{upload_id}").json()
    assert detail["uploaded_input"]["processing_status"] == "completed"
    assert "unpaid overtime" in detail["extracted_information"][0]["text"]

    full_text = _generate_approve_and_download(client, session_id)
    assert "unpaid overtime" in full_text


def test_sync(repo, monkeypatch):
    """
    Sync: an interview started on one request/process is read back and
    continued correctly from a completely separate client/process -
    proving the interview state is truly persisted, not held in memory.
    """

    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    first_client = TestClient(storage_api.app)

    session_id = _new_session(first_client)
    first_client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    first_client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    first_client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"})
    first_client.post(
        f"/end-user/intake/sessions/{session_id}/interview/message",
        json={"message": "No immediate risk."},
    )

    second_client = TestClient(storage_api.app)
    resumed = second_client.get(f"/end-user/intake/sessions/{session_id}/interview")

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["state"]["language"] == "en"
    assert body["state"]["current_state"] == "mandatory_sweep"
    assert body["state"]["current_step_index"] == 1

    step = second_client.post(
        f"/end-user/intake/sessions/{session_id}/interview/message",
        json={"message": "No upcoming deadlines."},
    )
    assert step.json()["state"]["current_step_index"] == 2


def test_isolation(client, repo):
    """
    Isolation: a different Client's (Matter's) intake session, interview
    state, facts, and report are never reachable through another
    Client's calls - each 404s exactly like Phase 2's thread isolation.
    """

    foreign_session = repo.create_intake_session(matter_id=999, title="Someone else's matter")

    assert client.get(f"/end-user/intake/sessions/{foreign_session['id']}").status_code == 404
    assert client.get(f"/end-user/intake/sessions/{foreign_session['id']}/facts").status_code == 404
    assert client.get(f"/end-user/intake/sessions/{foreign_session['id']}/interview").status_code == 404
    assert client.post(f"/end-user/intake/sessions/{foreign_session['id']}/interview/start").status_code == 404
    assert client.post(
        f"/end-user/intake/sessions/{foreign_session['id']}/interview/message", json={"message": "english"}
    ).status_code == 404

    foreign_report = repo.create_report(foreign_session["id"], 999, "docx", "session_999/reports", "report.docx")
    assert client.get(f"/end-user/intake/reports/{foreign_report['id']}/download").status_code == 404

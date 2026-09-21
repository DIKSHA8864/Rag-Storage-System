"""
Tests for the Client Intake API (app/api/intake_api.py) - full HTTP-level
flow: create a session, upload a file, poll its processing status/
extracted content, read the timeline, generate and download a report.
Uses a real TestClient (not calling handler functions directly) so
routing, isolation checks, and status codes are all exercised for real,
the same convention as tests/test_e2e_phase2.py.
"""

import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.storage.local_backend import LocalStorageBackend
from tests.conftest import _FakeQueue


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


def test_create_and_get_intake_session(client):
    created = client.post("/end-user/intake/sessions", json={"title": "New matter intake"})
    assert created.status_code == 200
    session_id = created.json()["id"]

    fetched = client.get(f"/end-user/intake/sessions/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "New matter intake"
    assert fetched.json()["status"] == "active"


def test_getting_a_nonexistent_session_404s(client):
    response = client.get("/end-user/intake/sessions/999")
    assert response.status_code == 404


def test_session_belonging_to_a_different_matter_404s(client, repo):
    """Direct proof of Matter isolation: a session created for a different matter_id must never be reachable through the API."""

    foreign_session = repo.create_intake_session(matter_id=999, title="Not yours")

    response = client.get(f"/end-user/intake/sessions/{foreign_session['id']}")
    assert response.status_code == 404


def test_upload_processes_a_text_file_synchronously_and_extracts_content(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    response = client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("notes.txt", io.BytesIO(b"Client statement text."), "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    upload_id = body["uploaded_input"]["id"]
    assert body["uploaded_input"]["media_type"] == "document"

    detail = client.get(f"/end-user/intake/uploads/{upload_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["uploaded_input"]["processing_status"] == "completed"
    assert "Client statement text." in detail_body["extracted_information"][0]["text"]


def test_upload_rejects_an_unsupported_extension(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    response = client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("virus.exe", io.BytesIO(b"bad"), "application/octet-stream")},
    )

    assert response.status_code == 400


def test_upload_to_a_foreign_session_404s(client):
    response = client.post(
        "/end-user/intake/sessions/999/uploads",
        files={"file": ("notes.txt", io.BytesIO(b"text"), "text/plain")},
    )
    assert response.status_code == 404


def test_timeline_records_upload_and_processing_events(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]
    client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("notes.txt", io.BytesIO(b"Some text."), "text/plain")},
    )

    timeline = client.get(f"/end-user/intake/sessions/{session_id}/timeline")
    assert timeline.status_code == 200
    event_types = {e["event_type"] for e in timeline.json()["events"]}
    assert "session_created" in event_types
    assert "input_uploaded" in event_types
    assert "input_processed" in event_types


def test_generate_and_download_docx_report(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]
    client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("notes.txt", io.BytesIO(b"Some client-submitted text."), "text/plain")},
    )

    generated = client.post(f"/end-user/intake/sessions/{session_id}/report", json={"format": "docx"})
    assert generated.status_code == 200
    report_id = generated.json()["id"]
    
    approved = client.post(f"/admin/reports/{report_id}/approve")
    assert approved.status_code == 200
    downloaded = client.get(f"/end-user/intake/reports/{report_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    document = Document(io.BytesIO(downloaded.content))
    full_text = "\n".join(p.text for p in document.paragraphs)
    assert "Some client-submitted text." in full_text


def test_generate_report_rejects_an_unknown_format(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    response = client.post(f"/end-user/intake/sessions/{session_id}/report", json={"format": "html"})
    assert response.status_code == 400


def test_downloading_a_foreign_report_404s(client):
    response = client.get("/end-user/intake/reports/999/download")
    assert response.status_code == 404

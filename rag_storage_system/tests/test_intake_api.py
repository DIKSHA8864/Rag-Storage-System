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


# ---------------------------------------------------------------------
# GET /end-user/intake/sessions/{id}/uploads - what the intake page's
# upload panel lists (image/audio/video/documents), each with its
# extracted content so far.
# ---------------------------------------------------------------------


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_listing_uploads_returns_each_file_with_its_extracted_content(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("statement.txt", io.BytesIO(b"I was fired after complaining."), "text/plain")},
    )
    client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("damage.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("voicemail.mp3", io.BytesIO(b"fake audio bytes"), "audio/mpeg")},
    )

    response = client.get(f"/end-user/intake/sessions/{session_id}/uploads")
    assert response.status_code == 200
    uploads = {u["uploaded_input"]["original_filename"]: u for u in response.json()["uploads"]}

    assert set(uploads) == {"statement.txt", "damage.png", "voicemail.mp3"}
    assert all(u["uploaded_input"]["processing_status"] == "completed" for u in uploads.values())

    assert uploads["statement.txt"]["uploaded_input"]["media_type"] == "document"
    assert "I was fired" in uploads["statement.txt"]["extracted_information"][0]["text"]

    image_types = {e["content_type"] for e in uploads["damage.png"]["extracted_information"]}
    assert image_types == {"ocr_text", "caption"}

    audio = uploads["voicemail.mp3"]["extracted_information"]
    assert [e["content_type"] for e in audio] == ["transcript"]
    # Default providers are "mock" - the UI must be able to tell the client this isn't a real transcript.
    assert audio[0]["is_mock"] is True


def test_listing_uploads_of_a_foreign_session_404s(client, repo):
    foreign_session = repo.create_intake_session(matter_id=999, title="Not yours")

    response = client.get(f"/end-user/intake/sessions/{foreign_session['id']}/uploads")
    assert response.status_code == 404


def test_unsupported_upload_gets_a_message_a_client_can_act_on(client):
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    response = client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("photo.heic", io.BytesIO(b"bytes"), "image/heic")},
    )

    assert response.status_code == 400
    assert "isn't supported" in response.json()["detail"]
    assert ".heic" in response.json()["detail"]


def test_a_crash_during_processing_marks_the_upload_failed_instead_of_processing_forever(client, monkeypatch):
    """Without this the client's upload panel would poll a "processing" status that never changes."""

    def _crash(filename, data):
        raise RuntimeError("database constraint violated")

    monkeypatch.setattr("app.jobs.intake_processing.process_uploaded_input", _crash)
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    upload = client.post(
        f"/end-user/intake/sessions/{session_id}/uploads",
        files={"file": ("clip.mp4", io.BytesIO(b"video bytes"), "video/mp4")},
    )
    assert upload.status_code == 200

    detail = client.get(f"/end-user/intake/uploads/{upload.json()['uploaded_input']['id']}").json()
    assert detail["uploaded_input"]["processing_status"] == "failed"
    assert detail["uploaded_input"]["status_detail"] == "An unexpected error occurred while processing this file."
    # The internal error text never reaches the client.
    assert "constraint" not in detail["uploaded_input"]["status_detail"]

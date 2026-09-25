"""Voice answers (transcribed for the client to review) and "Talk to a person" requests - app/api/voice_handoff_api.py."""

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key, require_end_user_key
from config.settings import get_settings


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    monkeypatch.setattr(get_settings(), "handoff_notify_emails", "")
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: None
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _signed_in_client(repo, email="alice@example.com", tenant_id=1):
    import uuid

    matter = repo.create_matter(f"Client {email}", uuid.uuid4().hex, tenant_id=tenant_id)
    invite = repo.create_end_user_invite(email, tenant_id, None)
    repo.activate_end_user(invite["id"], "hash", matter["id"], datetime.now(timezone.utc).isoformat())
    identity = {"id": matter["id"], "name": matter["name"], "tenant_id": tenant_id, "end_user_id": invite["id"]}
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: identity
    return identity


# ----------------------------------------------------------------------
# Voice
# ----------------------------------------------------------------------

def _transcribe(client, session_id, name="answer.webm", data=b"RIFF-audio"):
    return client.post(
        f"/end-user/intake/sessions/{session_id}/interview/transcribe", files={"file": (name, io.BytesIO(data), "audio/webm")}
    )


def test_voice_answers_need_a_real_speech_to_text_engine(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "stt_provider", "mock")
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    assert client.get("/end-user/intake/voice").json() == {"speech_to_text": False}
    assert _transcribe(client, session_id).status_code == 409


def test_spoken_answer_is_transcribed_but_not_recorded(client, repo, monkeypatch):
    import app.multimodal.speech_to_text as stt

    class FakeWhisper:
        name = "whisper"

        def transcribe(self, audio_bytes, filename):
            assert filename == "answer.webm"
            return " I worked about fifty hours a week. ", False

    monkeypatch.setattr(get_settings(), "stt_provider", "whisper")
    monkeypatch.setattr(stt, "get_stt_provider", lambda: FakeWhisper())
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    assert client.get("/end-user/intake/voice").json() == {"speech_to_text": True}
    assert _transcribe(client, session_id).json() == {"text": "I worked about fifty hours a week."}
    assert repo.list_intake_messages(session_id) == []  # only what the client then sends is recorded
    assert _transcribe(client, session_id, name="answer.exe").status_code == 400
    assert _transcribe(client, session_id, data=b"").status_code == 400
    assert _transcribe(client, 9999).status_code == 404


# ----------------------------------------------------------------------
# Talk to a person
# ----------------------------------------------------------------------

def test_client_asks_for_a_person_and_staff_work_the_queue(client, repo):
    alice = _signed_in_client(repo)
    session = client.post("/end-user/intake/sessions", json={"title": "Overtime"}).json()
    assert client.get("/end-user/handoff").json() is None

    created = client.post("/end-user/handoff", json={
        "intake_session_id": session["id"], "contact_method": "phone", "contact_value": "(213) 555-0100",
        "preferred_time": "Weekday mornings", "message": "I'd rather talk to someone.", "language": "en",
    })
    assert created.status_code == 200
    request = created.json()
    assert (request["status"], request["matter_id"]) == ("open", session["matter_id"])
    again = client.post("/end-user/handoff", json={"contact_method": "email", "contact_value": "alice@example.com"})
    assert again.json()["id"] == request["id"]  # one open request at a time
    assert "handoff_requested" in [e["event_type"] for e in repo.list_timeline_events(session["id"])]

    queue = client.get("/admin/handoffs?status=open").json()
    assert queue["open_count"] == 1 and [r["id"] for r in queue["requests"]] == [request["id"]]
    claimed = client.post(f"/admin/handoffs/{request['id']}/claim").json()
    assert (claimed["status"], claimed["claimed_by"]) == ("claimed", "test-owner@example.com")
    closed = client.post(f"/admin/handoffs/{request['id']}/close", json={"note": "Called, booked consult."}).json()
    assert (closed["status"], closed["closed_note"]) == ("closed", "Called, booked consult.")
    assert client.get("/end-user/handoff").json()["status"] == "closed"
    assert alice and client.post("/end-user/handoff", json={"contact_method": "email", "contact_value": "alice@example.com"}).json()["id"] != request["id"]


def test_handoff_validation_and_isolation(client, repo):
    _signed_in_client(repo)
    assert client.post("/end-user/handoff", json={"contact_method": "email", "contact_value": "not-an-email"}).status_code == 400
    assert client.post("/end-user/handoff", json={"contact_method": "phone", "contact_value": "12ab"}).status_code == 400
    assert client.post("/end-user/handoff", json={"contact_method": "fax", "contact_value": "555-0100"}).status_code == 422
    other = repo.create_intake_session(matter_id=999, title="Not yours")
    assert client.post("/end-user/handoff", json={
        "intake_session_id": other["id"], "contact_method": "phone", "contact_value": "2135550100"}).status_code == 404

    request = client.post("/end-user/handoff", json={"contact_method": "phone", "contact_value": "2135550100"}).json()
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "8", "email": "owner@two.example", "role": "owner", "tenant_id": 2,
    }
    assert client.get("/admin/handoffs").json()["requests"] == []
    assert client.post(f"/admin/handoffs/{request['id']}/claim").status_code == 404


def test_someone_elses_claim_is_respected(client, repo):
    _signed_in_client(repo)
    request = client.post("/end-user/handoff", json={"contact_method": "phone", "contact_value": "2135550100"}).json()
    client.post(f"/admin/handoffs/{request['id']}/claim")
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "3", "email": "paralegal@example.com", "role": "paralegal", "tenant_id": 1,
    }
    assert client.post(f"/admin/handoffs/{request['id']}/claim").status_code == 409


def test_staff_are_emailed_when_configured(client, repo, monkeypatch):
    import app.notifications.email_sender as email_sender

    sent = []

    class Recorder:
        def send(self, to_email, subject, body):
            sent.append((to_email, subject, body))

    monkeypatch.setattr(email_sender, "get_email_sender", lambda: Recorder())
    monkeypatch.setattr(get_settings(), "handoff_notify_emails", "intake@firm.example, partner@firm.example")
    _signed_in_client(repo)

    client.post("/end-user/handoff", json={"contact_method": "phone", "contact_value": "2135550100"})

    assert [to for to, _, _ in sent] == ["intake@firm.example", "partner@firm.example"]
    assert "2135550100" in sent[0][2]

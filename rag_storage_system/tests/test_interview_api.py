"""
Tests for the Guided Intake Engine API (app/api/interview_api.py) -
full HTTP-level English and Spanish walkthroughs, resuming an
in-progress interview from a brand new client/process, and proving the
mandatory sweep cannot be skipped. Uses a real TestClient, same
convention as tests/test_intake_api.py.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.intake_engine.mandatory_sweep import MANDATORY_SWEEP_QUESTIONS
from app.intake_engine.protected_activity import PROTECTED_ACTIVITY_QUESTIONS
from app.metadata.sqlite_repository import SQLiteMetadataRepository


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    return TestClient(storage_api.app)


def _new_session(client) -> int:
    return client.post("/end-user/intake/sessions", json={"title": "Interview"}).json()["id"]


def test_start_interview_returns_bilingual_opening_prompt(client):
    session_id = _new_session(client)

    response = client.post(f"/end-user/intake/sessions/{session_id}/interview/start")

    assert response.status_code == 200
    body = response.json()
    assert "English" in body["prompt"]
    assert body["state"]["current_state"] == "language_selection"


def test_starting_a_foreign_session_interview_404s(client, repo):
    foreign_session = repo.create_intake_session(matter_id=999, title="Not yours")

    response = client.post(f"/end-user/intake/sessions/{foreign_session['id']}/interview/start")
    assert response.status_code == 404


def test_full_english_walkthrough_reaches_completion(client):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")

    step = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    assert step.json()["state"]["current_state"] == "terms_acceptance"

    step = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"})
    assert step.json()["state"]["current_state"] == "mandatory_sweep"
    assert step.json()["state"]["terms_accepted_at"] is not None

    for question in MANDATORY_SWEEP_QUESTIONS:
        step = client.post(
            f"/end-user/intake/sessions/{session_id}/interview/message",
            json={"message": f"Answer for {question.key}"},
        )
    assert step.json()["state"]["current_state"] == "protected_activity"
    assert step.json()["state"]["mandatory_sweep_completed"] is True

    for question in PROTECTED_ACTIVITY_QUESTIONS:
        step = client.post(
            f"/end-user/intake/sessions/{session_id}/interview/message",
            json={"message": f"Answer for {question.key}"},
        )
    assert step.json()["state"]["current_state"] == "general_narrative"

    step = client.post(
        f"/end-user/intake/sessions/{session_id}/interview/message",
        json={"message": "I was fired after reporting a safety violation."},
    )
    assert step.json()["done"] is True
    assert step.json()["state"]["current_state"] == "complete"

    facts = client.get(f"/end-user/intake/sessions/{session_id}/facts").json()["facts"]
    fact_keys = {f["fact_key"] for f in facts}
    expected_keys = {q.key for q in MANDATORY_SWEEP_QUESTIONS} | {q.key for q in PROTECTED_ACTIVITY_QUESTIONS} | {"narrative_summary"}
    assert fact_keys == expected_keys


def test_full_spanish_walkthrough_uses_spanish_prompts_throughout(client):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")

    step = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "espanol"})
    assert step.json()["state"]["language"] == "es"
    assert "Acepto" in step.json()["reply"]

    step = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "Acepto"})
    assert step.json()["state"]["current_state"] == "mandatory_sweep"
    assert step.json()["reply"] == MANDATORY_SWEEP_QUESTIONS[0].prompt_es


def test_mandatory_sweep_question_cannot_be_skipped_with_blank_answer(client):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"})

    step = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "   "})

    assert step.json()["error"] is True
    assert step.json()["state"]["current_state"] == "mandatory_sweep"
    assert step.json()["state"]["current_step_index"] == 0


def test_resume_returns_current_state_and_full_transcript_mid_interview(client):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})

    resumed = client.get(f"/end-user/intake/sessions/{session_id}/interview")

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["state"]["current_state"] == "terms_acceptance"
    assert body["state"]["language"] == "en"
    assert [m["role"] for m in body["messages"]] == ["assistant", "user", "assistant"]


def test_resume_after_new_client_instance_continues_the_same_interview(repo, monkeypatch):
    """
    Proves persistence, not just in-memory state: a brand new
    TestClient/app instance (simulating a server restart or a
    different request) reads back exactly where the interview left
    off, then continues it successfully.
    """

    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    first_client = TestClient(storage_api.app)

    session_id = _new_session(first_client)
    first_client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    first_client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    first_client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"})

    second_client = TestClient(storage_api.app)

    resumed = second_client.get(f"/end-user/intake/sessions/{session_id}/interview")
    assert resumed.json()["state"]["current_state"] == "mandatory_sweep"

    step = second_client.post(
        f"/end-user/intake/sessions/{session_id}/interview/message",
        json={"message": "No immediate risk."},
    )
    assert step.json()["state"]["current_step_index"] == 1


def test_sending_a_message_without_starting_the_interview_first_is_rejected(client):
    session_id = _new_session(client)

    response = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    assert response.status_code == 409


def test_getting_a_foreign_session_facts_404s(client, repo):
    foreign_session = repo.create_intake_session(matter_id=999, title="Not yours")

    response = client.get(f"/end-user/intake/sessions/{foreign_session['id']}/facts")
    assert response.status_code == 404
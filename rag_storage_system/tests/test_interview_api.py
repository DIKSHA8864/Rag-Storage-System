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


_STORY = "I worked at Acme as a cook. They fired me two weeks after I complained about unpaid overtime."
_FOLLOW_UPS = ["How many hours a week did you usually work?", "Who did you complain to?"]
_KEY_DATES = ["April 2021", "2023", "March 2023", "June 2023"]


@pytest.fixture
def follow_ups(monkeypatch):
    """Stands in for Claude + the firm's question frameworks (app/intake_engine/follow_ups.py)."""

    import app.intake_engine.engine as engine

    calls = []

    def fake_generate(story, language, tenant_id):
        calls.append((story, language, tenant_id))
        return list(_FOLLOW_UPS)

    monkeypatch.setattr(engine, "generate_follow_up_questions", fake_generate)
    return calls


def _say(client, session_id, message):
    return client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": message}).json()


def test_full_english_walkthrough_reaches_completion(client, follow_ups):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")

    step = _say(client, session_id, "english")
    assert step["state"]["current_state"] == "terms_acceptance"

    step = _say(client, session_id, "I agree")
    assert step["state"]["current_state"] == "story"
    assert step["state"]["flow_version"] == 2
    assert step["state"]["terms_accepted_at"] is not None
    assert step["state"]["terms_accepted_ip"]  # recorded with the acceptance

    step = _say(client, session_id, _STORY)
    assert follow_ups == [(_STORY, "en", 1)]
    assert step["state"]["current_state"] == "follow_up"
    assert _FOLLOW_UPS[0] in step["reply"]

    step = _say(client, session_id, "About 55 hours.")
    assert step["reply"] == _FOLLOW_UPS[1]
    step = _say(client, session_id, "skip")
    assert step["state"]["current_state"] == "mandatory_sweep"
    assert MANDATORY_SWEEP_QUESTIONS[0].prompt_en in step["reply"]

    for question in MANDATORY_SWEEP_QUESTIONS:
        step = _say(client, session_id, f"Answer for {question.key}")
    assert step["state"]["current_state"] == "protected_activity"
    assert step["state"]["mandatory_sweep_completed"] is True

    for question in PROTECTED_ACTIVITY_QUESTIONS:
        step = _say(client, session_id, f"Answer for {question.key}")
    assert step["state"]["current_state"] == "timeline"

    for answer in _KEY_DATES:
        step = _say(client, session_id, answer)
        assert step["error"] is False
    assert step["state"]["current_state"] == "documents"

    step = _say(client, session_id, "Pay stubs and my termination letter.")
    assert step["done"] is True
    assert step["state"]["current_state"] == "complete"

    facts = client.get(f"/end-user/intake/sessions/{session_id}/facts").json()["facts"]
    by_key = {f["fact_key"]: f for f in facts}
    expected_keys = (
        {q.key for q in MANDATORY_SWEEP_QUESTIONS} | {q.key for q in PROTECTED_ACTIVITY_QUESTIONS}
        | {"client_story", "follow_up_1", "follow_up_2", "documents_available",
           "date_hired", "date_problem_started", "date_first_complaint", "date_last_day"}
    )
    assert set(by_key) == expected_keys
    assert by_key["follow_up_1"]["fact_value"] == f"Q: {_FOLLOW_UPS[0]}\nA: About 55 hours."
    assert by_key["follow_up_2"]["fact_value"].endswith("A: (skipped)")
    assert by_key["date_hired"]["fact_value"] == "2021-04 (answer: April 2021)"
    assert by_key["date_hired"]["category"] == "timeline"


def test_full_spanish_walkthrough_uses_spanish_prompts_throughout(client, follow_ups):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")

    step = _say(client, session_id, "espanol")
    assert step["state"]["language"] == "es"
    assert "Acepto" in step["reply"]

    step = _say(client, session_id, "Acepto")
    assert step["state"]["current_state"] == "story"
    assert "cuentenos" in step["reply"]

    _say(client, session_id, "Trabaje como cocinero y no me pagaron las horas extra.")
    assert follow_ups[-1][1] == "es"


def test_no_follow_ups_goes_straight_to_the_checklist(client, monkeypatch):
    import app.intake_engine.engine as engine

    monkeypatch.setattr(engine, "generate_follow_up_questions", lambda story, language, tenant_id: [])
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    _say(client, session_id, "english")
    _say(client, session_id, "I agree")

    step = _say(client, session_id, _STORY)

    assert step["state"]["current_state"] == "mandatory_sweep"
    assert step["reply"].endswith(MANDATORY_SWEEP_QUESTIONS[0].prompt_en)


def test_follow_ups_are_generated_once_and_survive_resume(client, follow_ups):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    _say(client, session_id, "english")
    _say(client, session_id, "I agree")
    _say(client, session_id, _STORY)

    resumed = client.get(f"/end-user/intake/sessions/{session_id}/interview").json()
    assert resumed["state"]["current_state"] == "follow_up"
    assert resumed["state"]["current_question_key"] == "follow_up_1"
    _say(client, session_id, "50")
    _say(client, session_id, "My manager")

    assert len(follow_ups) == 1


def test_a_date_out_of_order_is_rejected_and_asked_again(client, follow_ups):
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    step = _say(client, session_id, "english")
    for message in ["I agree", _STORY, "a", "b"] + ["No"] * (len(MANDATORY_SWEEP_QUESTIONS) + len(PROTECTED_ACTIVITY_QUESTIONS)):
        step = _say(client, session_id, message)
    assert step["state"]["current_question_key"] == "date_hired"

    step = _say(client, session_id, "April 2021")
    step = _say(client, session_id, "2019")  # problem started before being hired
    assert step["error"] is True
    assert "before the date you started working (2021-04)" in step["reply"]
    assert step["state"]["current_question_key"] == "date_problem_started"

    step = _say(client, session_id, "next tuesday maybe")
    assert step["error"] is True
    assert "couldn't read that as a date" in step["reply"]

    step = _say(client, session_id, "don't know")
    assert step["error"] is False
    assert step["state"]["current_question_key"] == "date_first_complaint"

    step = _say(client, session_id, "3000")
    assert step["error"] is True and "future" in step["reply"]


def test_an_interview_started_on_flow_1_finishes_on_flow_1(client, repo):
    """Interviews already in progress when flow 2 shipped keep their old order."""

    session_id = _new_session(client)
    repo.create_interview_state(session_id)  # a pre-0023 row: flow_version defaults to 1, no checklist snapshot
    repo.add_intake_message(session_id, "assistant", "Please select your language")

    _say(client, session_id, "english")
    step = _say(client, session_id, "I agree")
    assert step["state"]["current_state"] == "mandatory_sweep"
    assert step["state"]["flow_version"] == 1

    for _ in MANDATORY_SWEEP_QUESTIONS + PROTECTED_ACTIVITY_QUESTIONS:
        step = _say(client, session_id, "No")
    assert step["state"]["current_state"] == "general_narrative"
    step = _say(client, session_id, "I was fired.")
    assert step["done"] is True


def test_mandatory_sweep_question_cannot_be_skipped_with_blank_answer(client, monkeypatch):
    import app.intake_engine.engine as engine

    monkeypatch.setattr(engine, "generate_follow_up_questions", lambda story, language, tenant_id: [])
    session_id = _new_session(client)
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "I agree"})
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": _STORY})

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
    assert resumed.json()["state"]["current_state"] == "story"

    step = second_client.post(
        f"/end-user/intake/sessions/{session_id}/interview/message",
        json={"message": _STORY},
    )
    assert step.json()["state"]["current_state"] == "mandatory_sweep"


def test_sending_a_message_without_starting_the_interview_first_is_rejected(client):
    session_id = _new_session(client)

    response = client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "english"})
    assert response.status_code == 409


def test_getting_a_foreign_session_facts_404s(client, repo):
    foreign_session = repo.create_intake_session(matter_id=999, title="Not yours")

    response = client.get(f"/end-user/intake/sessions/{foreign_session['id']}/facts")
    assert response.status_code == 404

def test_every_question_shows_its_number_out_of_the_total(client, follow_ups):
    """The client always sees 'Question X of Y': consecutive numbers, ending at Y."""

    session_id = _new_session(client)
    start = client.post(f"/end-user/intake/sessions/{session_id}/interview/start").json()
    assert start["state"]["question_number"] is None

    _say(client, session_id, "english")
    step = _say(client, session_id, "I agree")

    answers = iter([_STORY, "a", "b"] + ["No"] * (len(MANDATORY_SWEEP_QUESTIONS) + len(PROTECTED_ACTIVITY_QUESTIONS)) + _KEY_DATES + ["none"])
    seen = []
    while step["state"]["current_state"] != "complete":
        seen.append(step["state"]["question_number"])
        step = _say(client, session_id, next(answers))
        assert step["error"] is False

    expected_total = 1 + len(_FOLLOW_UPS) + len(MANDATORY_SWEEP_QUESTIONS) + len(PROTECTED_ACTIVITY_QUESTIONS) + 4 + 1
    assert seen == list(range(1, expected_total + 1))
    assert step["state"]["total_questions"] == expected_total
    assert step["state"]["question_number"] is None

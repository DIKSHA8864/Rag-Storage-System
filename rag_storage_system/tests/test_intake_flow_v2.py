"""
Guided intake flow 2: key-date parsing and chronology checks
(app/intake_engine/timeline.py), follow-up questions drawn only from the
firm's question frameworks (app/intake_engine/follow_ups.py), and the
owner-editable checklist (app/api/intake_checklist_api.py) - including
that an edit never changes an interview already in progress.
"""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.intake_engine import follow_ups, timeline
from app.intake_engine.mandatory_sweep import MANDATORY_SWEEP_QUESTIONS, REQUIRED_CHECKLIST_KEYS
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key

TODAY = date(2026, 9, 25)
Q = {q.key: q for q in timeline.TIMELINE_QUESTIONS}


# ----------------------------------------------------------------------
# Key dates
# ----------------------------------------------------------------------

@pytest.mark.parametrize("raw, language, value", [
    ("April 2023", "en", "2023-04"),
    ("04/15/2023", "en", "2023-04-15"),
    ("15/04/2023", "es", "2023-04-15"),
    ("15 de abril de 2023", "es", "2023-04-15"),
    ("abril 2023", "es", "2023-04"),
    ("2021", "en", "2021"),
    ("2023-04", "en", "2023-04"),
])
def test_dates_keep_their_real_precision(raw, language, value):
    answer = timeline.parse_date_answer(raw, language)
    assert (answer.kind, answer.value) == (timeline.KIND_DATE, value)


def test_a_month_answer_covers_the_whole_month():
    answer = timeline.parse_date_answer("February 2024", "en")
    assert (answer.earliest, answer.latest) == (date(2024, 2, 1), date(2024, 2, 29))


@pytest.mark.parametrize("raw, kind", [
    ("Don't know", timeline.KIND_UNKNOWN), ("no se", timeline.KIND_UNKNOWN), ("none", timeline.KIND_NONE),
    ("nunca", timeline.KIND_NONE), ("still working", timeline.KIND_STILL_EMPLOYED),
    ("sometime last spring", timeline.KIND_INVALID), ("March 5", timeline.KIND_INVALID), ("", timeline.KIND_INVALID),
])
def test_non_date_answers(raw, kind):
    assert timeline.parse_date_answer(raw, "en").kind == kind


def test_none_and_still_working_are_only_accepted_where_they_make_sense():
    none = timeline.parse_date_answer("none", "en")
    still = timeline.parse_date_answer("still working", "en")

    assert timeline.answer_error(Q["date_first_complaint"], none, {}, TODAY, "en") is None
    assert timeline.answer_error(Q["date_hired"], none, {}, TODAY, "en") is not None
    assert timeline.answer_error(Q["date_last_day"], still, {}, TODAY, "en") is None
    assert timeline.answer_error(Q["date_hired"], still, {}, TODAY, "en") is not None


def test_future_dates_and_clear_contradictions_are_flagged_overlaps_are_not():
    hired = timeline.parse_date_answer("April 2023", "en")
    recorded = {"date_hired": hired}

    assert "future" in timeline.answer_error(Q["date_hired"], timeline.parse_date_answer("2030", "en"), {}, TODAY, "en")
    error = timeline.answer_error(Q["date_last_day"], timeline.parse_date_answer("March 2023", "en"), recorded, TODAY, "en")
    assert "2023-04" in error
    # "2023" could be April 2023 or later - not a contradiction.
    assert timeline.answer_error(Q["date_problem_started"], timeline.parse_date_answer("2023", "en"), recorded, TODAY, "en") is None
    # Unknown earlier dates don't block anything.
    assert timeline.answer_error(
        Q["date_last_day"], timeline.parse_date_answer("2020", "en"),
        {"date_hired": timeline.parse_date_answer("don't know", "en")}, TODAY, "en",
    ) is None


def test_spanish_errors_are_in_spanish():
    error = timeline.answer_error(Q["date_hired"], timeline.parse_date_answer("tal vez", "es"), {}, TODAY, "es")
    assert "No pude entender" in error


def test_recorded_values_round_trip():
    assert timeline.recorded_value("2023-04 (answer: April 2023)") == timeline.parse_date_answer("April 2023", "en")
    assert timeline.recorded_value("2023-04-15 (answer: 4/15/2023)").earliest == date(2023, 4, 15)
    assert timeline.recorded_value("unknown (answer: don't know)").kind == timeline.KIND_UNKNOWN


# ----------------------------------------------------------------------
# Follow-up questions
# ----------------------------------------------------------------------

class _FakeMessages:
    def __init__(self, text, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error, self.calls = text, stop_reason, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)], stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


@pytest.fixture
def claude(monkeypatch):
    import anthropic

    from config.settings import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    fake = _FakeMessages('{"questions": ["How many hours did you work each week?", "Who did you complain to?"]}')
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: SimpleNamespace(messages=fake))
    return fake


_FRAMEWORK = [{"filename": "wage_framework.docx", "chunk_text": "Ask: weekly hours worked; who received the complaint."}]


def test_follow_ups_come_from_the_framework_passages(claude, monkeypatch):
    seen = {}

    def fake_passages(story, tenant_id):
        seen.update(story=story, tenant_id=tenant_id)
        return _FRAMEWORK

    monkeypatch.setattr(follow_ups, "_framework_passages", fake_passages)

    questions = follow_ups.generate_follow_up_questions("I was not paid overtime.", "es", tenant_id=3)

    assert questions == ["How many hours did you work each week?", "Who did you complain to?"]
    assert seen == {"story": "I was not paid overtime.", "tenant_id": 3}
    call = claude.calls[0]
    assert "Spanish" in call["system"]
    assert "<story>\nI was not paid overtime.\n</story>" in call["messages"][0]["content"]
    assert "wage_framework.docx" in call["messages"][0]["content"]


def test_no_framework_passages_means_no_follow_ups_and_no_model_call(claude, monkeypatch):
    monkeypatch.setattr(follow_ups, "_framework_passages", lambda story, tenant_id: [])

    assert follow_ups.generate_follow_up_questions("A story.", "en", 1) == []
    assert claude.calls == []


def test_follow_ups_fail_quietly(claude, monkeypatch):
    monkeypatch.setattr(follow_ups, "_framework_passages", lambda story, tenant_id: _FRAMEWORK)

    claude.error = RuntimeError("overloaded")
    assert follow_ups.generate_follow_up_questions("A story.", "en", 1) == []

    claude.error, claude.stop_reason = None, "max_tokens"
    assert follow_ups.generate_follow_up_questions("A story.", "en", 1) == []

    def broken(story, tenant_id):
        raise ConnectionError("no index")

    monkeypatch.setattr(follow_ups, "_framework_passages", broken)
    assert follow_ups.generate_follow_up_questions("A story.", "en", 1) == []


def test_without_an_api_key_there_are_no_follow_ups(monkeypatch):
    from config.settings import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    assert follow_ups.generate_follow_up_questions("A story.", "en", 1) == []


def test_parse_questions_caps_dedupes_and_rejects_garbage():
    many = '{"questions": ["a?", "a?", "b?", " ", "c?", "d?", "e?"]}'
    assert follow_ups.parse_questions(many) == ["a?", "b?", "c?", "d?"]
    assert follow_ups.parse_questions("not json") == []
    assert follow_ups.parse_questions('{"questions": "a?"}') == []


# ----------------------------------------------------------------------
# Owner-editable checklist
# ----------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    import app.intake_engine.engine as engine

    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    monkeypatch.setattr(engine, "generate_follow_up_questions", lambda story, language, tenant_id: [])
    return TestClient(storage_api.app)


def _as_owner_of(tenant_id: int):
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "9", "email": f"owner{tenant_id}@example.com", "role": "owner", "tenant_id": tenant_id,
    }


def _edited_checklist(client) -> list[dict]:
    items = client.get("/admin/intake/checklist").json()["items"]
    for item in items:
        if item["key"] == "overtime":
            item["prompt_en"] = "Did you work overtime without overtime pay?"
        if item["key"] == "other_representation":
            item["is_active"] = False
    items.append({"key": "tips", "prompt_en": "Did your employer keep any of your tips?", "prompt_es": "Su empleador se quedo con sus propinas?"})
    return items


def test_checklist_defaults_then_saves_edits(client):
    body = client.get("/admin/intake/checklist").json()
    assert body["customized"] is False
    assert [i["key"] for i in body["items"]] == [q.key for q in MANDATORY_SWEEP_QUESTIONS]
    assert {i["key"] for i in body["items"] if i["required"]} == REQUIRED_CHECKLIST_KEYS

    saved = client.put("/admin/intake/checklist", json={"items": _edited_checklist(client)})

    assert saved.status_code == 200
    body = saved.json()
    assert body["customized"] is True
    by_key = {i["key"]: i for i in body["items"]}
    assert by_key["overtime"]["prompt_en"] == "Did you work overtime without overtime pay?"
    assert by_key["other_representation"]["is_active"] is False
    assert body["items"][-1]["key"] == "tips"

    reset = client.delete("/admin/intake/checklist").json()
    assert reset["customized"] is False


@pytest.mark.parametrize("change, message", [
    (lambda items: [i for i in items if i["key"] != "leave"], "Required topics can't be removed: leave"),
    (lambda items: [{**i, "is_active": i["key"] != "overtime"} for i in items], "required topic"),
    (lambda items: items + [dict(items[0])], "appears twice"),
    (lambda items: items + [{"key": "date_hired", "prompt_en": "x", "prompt_es": "y"}], "another part of the interview"),
    (lambda items: items + [{"key": "follow_up_1", "prompt_en": "x", "prompt_es": "y"}], "another part of the interview"),
    (lambda items: items + [{"key": "Bad Key", "prompt_en": "x", "prompt_es": "y"}], "lowercase"),
    (lambda items: items + [{"key": "tips", "prompt_en": "Tips?", "prompt_es": "  "}], "Spanish"),
    (lambda items: [], "at least one"),
])
def test_invalid_checklists_are_rejected(client, change, message):
    items = client.get("/admin/intake/checklist").json()["items"]

    response = client.put("/admin/intake/checklist", json={"items": change(items)})

    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert client.get("/admin/intake/checklist").json()["customized"] is False


def test_checklist_is_per_organization(client, repo):
    with repo._connect() as conn:
        conn.execute("INSERT OR IGNORE INTO tenants (id, name, slug, created_at) VALUES (2, 'Second', 'second', '2026-01-01')")
    client.put("/admin/intake/checklist", json={"items": _edited_checklist(client)})

    _as_owner_of(2)
    try:
        assert client.get("/admin/intake/checklist").json()["customized"] is False
    finally:
        storage_api.app.dependency_overrides.pop(require_admin_key, None)


def test_checklist_requires_the_owner_role(client):
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "5", "email": "staff@example.com", "role": "staff", "tenant_id": 1,
    }
    try:
        assert client.get("/admin/intake/checklist").status_code == 403
    finally:
        storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _start_and_reach_checklist(client) -> int:
    session_id = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]
    client.post(f"/end-user/intake/sessions/{session_id}/interview/start")
    for message in ["english", "I agree"]:
        client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": message})
    return session_id


def _checklist_keys_asked(client, session_id) -> list[str]:
    client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "My story."})
    keys = []
    while True:
        state = client.get(f"/end-user/intake/sessions/{session_id}/interview").json()["state"]
        if state["current_state"] != "mandatory_sweep":
            return keys
        keys.append(state["current_question_key"])
        client.post(f"/end-user/intake/sessions/{session_id}/interview/message", json={"message": "No"})


def test_new_interviews_use_the_edited_checklist_and_old_ones_keep_theirs(client):
    started_before = _start_and_reach_checklist(client)

    client.put("/admin/intake/checklist", json={"items": _edited_checklist(client)})
    started_after = _start_and_reach_checklist(client)

    before_keys = _checklist_keys_asked(client, started_before)
    after_keys = _checklist_keys_asked(client, started_after)

    assert before_keys == [q.key for q in MANDATORY_SWEEP_QUESTIONS]
    assert "other_representation" not in after_keys
    assert after_keys[-1] == "tips"
    facts = client.get(f"/end-user/intake/sessions/{started_after}/facts").json()["facts"]
    assert any(f["fact_key"] == "tips" and f["category"] == "mandatory_sweep" for f in facts)


def test_terms_acceptance_records_time_version_and_ip(client, repo):
    session_id = _start_and_reach_checklist(client)

    state = repo.get_interview_state(session_id)
    assert state["terms_accepted_at"] and state["terms_version"]
    assert state["terms_accepted_ip"] == "testclient"  # Starlette's TestClient address
    events = [e["description"] for e in repo.list_timeline_events(session_id) if e["event_type"] == "terms_accepted"]
    assert events == [f"Terms {state['terms_version']} accepted from IP testclient."]

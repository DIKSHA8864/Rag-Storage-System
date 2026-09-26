"""
The dashboard's "Today" panel (app/api/today_api.py), and the pending
reports list it shares a visibility rule with: the caller's organization
only, and an attorney/paralegal only sees assigned matters.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _as(role="owner", tenant_id=1, sub="1"):
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": sub, "email": f"{role}@example.com", "role": role, "tenant_id": tenant_id,
    }


def _midnight() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _intake(repo, matter_id, title, state=None, report=False):
    session = repo.create_intake_session(matter_id=matter_id, title=title)
    if state:
        repo.create_interview_state(session["id"])
        repo.update_interview_state(session["id"], "en", state, 0, None, None, state == "complete")
    if report:
        row = repo.create_report(session["id"], matter_id, "pdf", "c", "r.pdf")
        repo.create_report_review(row["id"])
    return session


@pytest.fixture
def firm(repo):
    mine = repo.create_matter("Lopez case", "h1", tenant_id=1)
    other = repo.create_matter("Other firm case", "h2", tenant_id=2)
    _intake(repo, mine["id"], "Intake - Maria Lopez", state="complete", report=True)
    _intake(repo, mine["id"], "Intake - Sam Park", state="mandatory_sweep")
    _intake(repo, other["id"], "Intake - Other Client", state="complete", report=True)
    repo.create_handoff_request(1, mine["id"], None, None, "phone", "555-0100", "", "", "en")
    repo.create_handoff_request(2, other["id"], None, None, "phone", "555-0199", "", "", "en")
    for result in ("grounded", "insufficient_evidence"):
        repo.add_llm_usage_log(None, None, "end_user_query", "n/a", 0, 0, 10, query_text="q",
                               retrieved_chunk_ids=[], retrieved_chunk_scores=[], citation_check_result=result, tenant_id=1)
    repo.add_llm_usage_log(None, None, "end_user_query", "n/a", 0, 0, 10, query_text="q", retrieved_chunk_ids=[],
                           retrieved_chunk_scores=[], citation_check_result="grounded", tenant_id=2)
    return mine, other


def test_today_counts_only_this_organization(client, firm):
    mine, _ = firm
    body = client.get("/admin/today", params={"since": _midnight()}).json()

    assert [i["title"] for i in body["new_intakes"]] == ["Intake - Sam Park", "Intake - Maria Lopez"]
    assert {i["matter_id"] for i in body["new_intakes"]} == {mine["id"]}
    assert body["intakes_started"] == 2 and body["intakes_completed"] == 1
    assert body["questions_asked"] == 2 and body["no_authority"] == 1
    assert body["reports_pending"] == 1
    assert body["requests_open"] == 1 and body["requests_claimed"] == 0


def test_attorney_sees_only_assigned_matters(client, repo, firm):
    mine, _ = firm
    _as("attorney", sub="7")
    assert client.get("/admin/today").json()["new_intakes"] == []
    assert client.get("/admin/today").json()["reports_pending"] == 0

    repo.create_matter_assignment(7, mine["id"], "attorney")
    body = client.get("/admin/today").json()
    assert body["intakes_started"] == 2 and body["reports_pending"] == 1


def test_since_is_the_viewers_midnight_but_never_trusted_blindly(client, firm):
    later = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert client.get("/admin/today", params={"since": later}).json()["since"] == _midnight()  # future -> server midnight
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert client.get("/admin/today", params={"since": old}).json()["since"] == _midnight()
    assert client.get("/admin/today", params={"since": "not a date"}).status_code == 200


def test_pending_reports_list_never_shows_another_organizations_reports(client, firm):
    mine, other = firm
    reports = client.get("/admin/reports/pending").json()["reports"]
    assert len(reports) == 1

    _as("owner", tenant_id=2)
    theirs = client.get("/admin/reports/pending").json()["reports"]
    assert len(theirs) == 1 and theirs[0]["report_id"] != reports[0]["report_id"]

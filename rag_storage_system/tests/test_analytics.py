"""Owner analytics (app/api/analytics_api.py) - real counts from existing records, per organization, cost only when priced."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key
from config.settings import get_settings


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    monkeypatch.setattr(get_settings(), "llm_prices", "")
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _log(repo, result, tenant_id=1, chunks=None, model="claude-opus-5", question=True, tokens=(1000, 200), latency=900):
    repo.add_llm_usage_log(
        None, None, "owner_research" if question else "relevance_filter", model, tokens[0], tokens[1], latency,
        query_text="q" if question else None, retrieved_chunk_ids=chunks or [], retrieved_chunk_scores=[0.5] * len(chunks or []),
        citation_check_result=result, tenant_id=tenant_id,
    )


def test_questions_outcomes_tokens_and_top_sources(client, repo, _fake_vector_store):
    for chunk_id, filename in (("c1", "overtime.pdf"), ("c2", "overtime.pdf"), ("c3", "leave.pdf")):
        _fake_vector_store.upsert_chunk_embedding(chunk_id=chunk_id, document_id="d", category="Wage", filename=filename,
                                                  chunk_text="t", embedding=[0.0] * 384, model_name="m", tenant_id=1)
    _log(repo, "grounded", chunks=["c1", "c2"], latency=800)
    _log(repo, "grounded", chunks=["c1", "c3"], latency=1200)
    _log(repo, "insufficient_evidence", model="n/a", tokens=(0, 0), latency=50)
    _log(repo, "relevance_check_unavailable", model="n/a", tokens=(0, 0), latency=40)
    _log(repo, None, question=False, tokens=(300, 10))  # a relevance-filter call: tokens, not a question
    _log(repo, "grounded", tenant_id=2, chunks=["c1"])  # another organization

    body = client.get("/admin/analytics?days=7").json()

    questions = body["questions"]
    assert questions["total"] == 4
    assert questions["outcomes"] == {"grounded": 2, "insufficient_evidence": 1, "relevance_check_unavailable": 1}
    assert questions["honest_gap_rate"] == 0.25
    assert len(questions["per_day"]) == 7 and questions["per_day"][-1]["count"] == 4
    assert questions["median_latency_ms"] == 800
    assert body["usage"]["calls"] == 5
    assert body["usage"]["input_tokens"] == 2300
    assert body["usage"]["estimated_cost_usd"] is None  # not priced -> not guessed
    assert body["top_sources"] == [
        {"category": "Wage", "filename": "overtime.pdf", "count": 3},
        {"category": "Wage", "filename": "leave.pdf", "count": 1},
    ]


def test_cost_is_shown_only_when_every_used_model_is_priced(client, repo, monkeypatch):
    _log(repo, "grounded", tokens=(1_000_000, 100_000))
    monkeypatch.setattr(get_settings(), "llm_prices", '{"claude-opus-5": [15, 75]}')

    usage = client.get("/admin/analytics").json()["usage"]
    assert usage["estimated_cost_usd"] == 22.5
    assert usage["by_model"][0]["estimated_cost_usd"] == 22.5

    _log(repo, "grounded", model="claude-other", tokens=(10, 10))
    assert client.get("/admin/analytics").json()["usage"]["estimated_cost_usd"] is None

    monkeypatch.setattr(get_settings(), "llm_prices", "not json")
    assert client.get("/admin/analytics").json()["usage"]["estimated_cost_usd"] is None


def test_intake_funnel(client, repo):
    matter = repo.create_matter("Client", "hash-1")
    started = repo.create_intake_session(matter["id"], "A")
    repo.create_intake_session(matter["id"], "B")  # never started
    repo.create_interview_state(started["id"])
    repo.update_interview_state(started["id"], "en", "complete", 0, datetime.now(timezone.utc).isoformat(), "2026-01", True)
    report = repo.create_report(started["id"], matter["id"], "pdf", "c", "r.pdf")
    repo.create_report_review(report["id"])
    repo.update_report_review(report["id"], "approved", "owner@example.com")
    other_tenant = repo.create_matter("Other", "hash-2", tenant_id=2)
    repo.create_intake_session(other_tenant["id"], "Not ours")

    intake = client.get("/admin/analytics").json()["intake"]

    assert (intake["sessions"], intake["interviews_started"], intake["terms_accepted"], intake["interviews_completed"]) == (2, 1, 1, 1)
    assert (intake["reports_generated"], intake["reports_approved"]) == (1, 1)


def test_old_activity_is_outside_the_window(client, repo):
    _log(repo, "grounded")
    with repo._connect() as conn:
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        conn.execute("UPDATE llm_usage_log SET created_at = ?", (old,))

    assert client.get("/admin/analytics?days=30").json()["questions"]["total"] == 0
    assert client.get("/admin/analytics?days=60").json()["questions"]["total"] == 1


def test_analytics_is_owner_only(client):
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "3", "email": "attorney@example.com", "role": "attorney", "tenant_id": 1,
    }
    assert client.get("/admin/analytics").status_code == 403


def test_admin_stats_counts_only_the_callers_organization(client, repo):
    repo.upsert_document("Wage", "ours.pdf", ".pdf", 10, "sha-1", tenant_id=1)
    repo.upsert_document("Wage", "theirs.pdf", ".pdf", 10, "sha-2", tenant_id=2)

    assert client.get("/admin/stats").json()["total_documents"] == 1
    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "9", "email": "o@two.example", "role": "owner", "tenant_id": 2,
    }
    assert client.get("/admin/stats").json()["total_documents"] == 1

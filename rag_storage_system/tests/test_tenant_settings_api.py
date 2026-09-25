"""
Retrieval settings and the disclaimer belong to one organization: an
admin of one firm can never change - or see - another firm's. Real
auth (the conftest bypass is removed), two tenants' owner tokens.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key


@pytest.fixture
def client(tmp_path, monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db"))
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _owner(tenant_id: int) -> dict:
    token = create_access_token(owner_id=tenant_id, email=f"owner{tenant_id}@example.com", tenant_id=tenant_id, role="owner")
    return {"Authorization": f"Bearer {token}"}


def test_retrieval_settings_are_per_organization(client):
    saved = client.put(
        "/admin/retrieval-settings", json={"top_k": 9, "score_threshold": 0.5, "min_chunks": 2}, headers=_owner(2)
    )
    assert saved.status_code == 200

    assert client.get("/admin/retrieval-settings", headers=_owner(2)).json()["top_k"] == 9
    firm_one = client.get("/admin/retrieval-settings", headers=_owner(1)).json()
    assert (firm_one["top_k"], firm_one["score_threshold"], firm_one["updated_by"]) == (5, 0.3, None)


def test_disclaimer_is_per_organization(client):
    assert client.put("/admin/disclaimer", json={"text": "Firm two only."}, headers=_owner(2)).status_code == 200

    assert client.get("/admin/disclaimer", headers=_owner(2)).json()["text"] == "Firm two only."
    assert client.get("/admin/disclaimer", headers=_owner(1)).json()["text"] != "Firm two only."


def test_query_log_shows_only_this_organizations_questions_newest_first(client):
    repo = storage_api.metadata_repository
    for tenant_id, query in [(1, "firm one old"), (2, "firm two secret"), (1, "firm one new")]:
        repo.add_llm_usage_log(
            matter_id=None, intake_session_id=None, purpose="end_user_query", model="n/a",
            input_tokens=0, output_tokens=0, latency_ms=12, query_text=query,
            retrieved_chunk_ids=["c-1", "c-2"], retrieved_chunk_scores=[0.41, 0.52],
            citation_check_result="insufficient_evidence", tenant_id=tenant_id,
        )
    repo.add_llm_usage_log(  # a non-question call (e.g. image description) - hidden by default
        matter_id=None, intake_session_id=None, purpose="vision_captioning", model="claude-opus-5",
        input_tokens=10, output_tokens=5, latency_ms=900, tenant_id=1,
    )

    body = client.get("/admin/query-log", headers=_owner(1)).json()

    assert body["total"] == 2
    assert [e["query_text"] for e in body["entries"]] == ["firm one new", "firm one old"]
    assert body["entries"][0]["retrieved_count"] == 2
    assert body["entries"][0]["top_score"] == 0.52
    assert "firm two secret" not in str(body)

    everything = client.get("/admin/query-log?questions_only=false", headers=_owner(1)).json()
    assert everything["total"] == 3


def test_query_log_is_owner_only(client):
    token = create_access_token(owner_id=5, email="para@example.com", tenant_id=1, role="paralegal")
    assert client.get("/admin/query-log", headers={"Authorization": f"Bearer {token}"}).status_code == 403

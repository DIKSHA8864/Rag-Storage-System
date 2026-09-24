"""
Tests for POST /admin/matters/{matter_id}/research
(app/api/storage_api.py's matter_research_ask()) - the Matter-scoped
counterpart to POST /research/ask (tests/test_owner_research.py),
reusing the exact same shared implementation
(app/analysis/answer_generation.py's stream_grounded_answer()).

Focus here is the relevance-gate fix: Matter Research must never
generate a substantive answer "grounded" in a retrieved chunk that
only shares vocabulary with the question (a CGL/D&O/Workers'
Compensation/defamation document mentioning "employment",
"termination", "discrimination", or "complaint" without actually
being about the same legal issue) - see app/analysis/relevance_guard.py.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)

    monkeypatch.setattr(storage_api, "metadata_repository", repo)

    yield TestClient(storage_api.app)

    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def _owner_header(owner_id: int = 1, role: str = "owner", tenant_id: int = 1) -> dict:
    token = create_access_token(owner_id=owner_id, email=f"user{owner_id}@example.com", role=role, tenant_id=tenant_id)
    return {"Authorization": f"Bearer {token}"}


def _hit(filename: str, category: str, score: float, text: str) -> dict:
    return {
        "chunk_id": filename, "document_id": filename, "category": category, "filename": filename,
        "chunk_text": text, "section": "1.1", "start_page": 1, "end_page": 1, "final_score": score,
    }


def _cgl_exclusion_hit() -> dict:
    return _hit(
        "cgl_policy_exclusions.pdf", "Insurance", 0.42,
        "This CGL policy excludes claims arising from employment-related practices "
        "including termination, discrimination, and harassment complaints.",
    )


def _employment_hit() -> dict:
    return _hit(
        "employment_handbook.pdf", "HR Policy", 0.85,
        "An employee may not be terminated in retaliation for filing a discrimination complaint.",
    )


def _fake_relevance_client(response_text: str):
    block = SimpleNamespace(type="text", text=response_text)
    usage = SimpleNamespace(input_tokens=5, output_tokens=5)
    response = SimpleNamespace(content=[block], usage=usage)

    class _FakeMessages:
        def create(self, **kwargs):
            return response

    return SimpleNamespace(messages=_FakeMessages())


def test_matter_research_answers_a_genuinely_supported_question(client, repo, monkeypatch):
    matter = repo.create_matter("Acme Corp", "hash-a")
    monkeypatch.setattr(
        storage_api, "retrieve_for_matter",
        lambda query, matter_id, top_k, score_threshold=0.0, tenant_id=1: [_employment_hit()],
    )

    response = client.post(
        f"/admin/matters/{matter['id']}/research",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["filename"] == "employment_handbook.pdf"


def test_matter_research_refuses_to_answer_from_a_loosely_keyword_matched_document(client, repo, monkeypatch):
    """Reproduces the reported bug for Matter Research specifically: an unrelated CGL exclusions clause must not become a source or ground an answer."""

    matter = repo.create_matter("Acme Corp", "hash-b")
    monkeypatch.setattr(
        storage_api, "retrieve_for_matter",
        lambda query, matter_id, top_k, score_threshold=0.0, tenant_id=1: [_cgl_exclusion_hit()],
    )
    monkeypatch.setattr(
        "app.analysis.relevance_guard.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", analysis_model="claude-opus-5"),
    )
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_relevance_client("[]"))

    response = client.post(
        f"/admin/matters/{matter['id']}/research",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "No authority on this point was found in the firm's legal library."
    assert body["sources"] == []
    assert "cgl_policy_exclusions.pdf" not in str(body)


def test_matter_research_drops_the_unrelated_source_but_keeps_the_relevant_one(client, repo, monkeypatch):
    matter = repo.create_matter("Acme Corp", "hash-c")
    monkeypatch.setattr(
        storage_api, "retrieve_for_matter",
        lambda query, matter_id, top_k, score_threshold=0.0, tenant_id=1: [_employment_hit(), _cgl_exclusion_hit()],
    )
    monkeypatch.setattr(
        "app.analysis.relevance_guard.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", analysis_model="claude-opus-5"),
    )
    # Only index 0 (the employment handbook) is materially relevant.
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_relevance_client("[0]"))

    response = client.post(
        f"/admin/matters/{matter['id']}/research",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(),
    )

    assert response.status_code == 200
    body = response.json()
    filenames = {s["filename"] for s in body["sources"]}
    assert filenames == {"employment_handbook.pdf"}


def test_matter_research_still_honors_tenant_isolation_with_the_relevance_gate_active(client, repo, monkeypatch):
    """The relevance gate is an additional filter, never a replacement for existing Matter/tenant isolation."""

    tenant_a_matter = repo.create_matter("Tenant A Corp", "hash-d", tenant_id=1)
    tenant_b_matter = repo.create_matter("Tenant B Corp", "hash-e", tenant_id=2)
    monkeypatch.setattr(
        storage_api, "retrieve_for_matter",
        lambda query, matter_id, top_k, score_threshold=0.0, tenant_id=1: [_employment_hit()],
    )

    cross_tenant_response = client.post(
        f"/admin/matters/{tenant_b_matter['id']}/research",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(tenant_id=1),
    )
    assert cross_tenant_response.status_code == 404

    own_tenant_response = client.post(
        f"/admin/matters/{tenant_a_matter['id']}/research",
        json={"query": "Can an employee be fired for filing a discrimination complaint?"},
        headers=_owner_header(tenant_id=1),
    )
    assert own_tenant_response.status_code == 200

"""
Step 24 - Multi-Tenancy Foundation: real, backend-enforced isolation
between two different tenants (firms/organizations), not just two
different Matters within the same firm (that's tests/test_threads_and_matters.py
and tests/test_matter_workspace.py). Auth is NOT bypassed here -
bypassing it would make the isolation assertions meaningless.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(repo, monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", repo)

    yield TestClient(storage_api.app)

    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def _owner_header(tenant_id: int, owner_id: int = 1, role: str = "owner") -> dict:
    token = create_access_token(
        owner_id=owner_id, email=f"owner-{tenant_id}@example.com", tenant_id=tenant_id, role=role
    )
    return {"Authorization": f"Bearer {token}"}


def test_owner_cannot_see_another_tenants_matter(client, repo):
    """The core Step 24 guarantee: a Matter belonging to a different tenant 404s, even for role='owner'."""

    tenant_a_matter = repo.create_matter("Tenant A Corp", "hash-a", tenant_id=1)
    tenant_b_matter = repo.create_matter("Tenant B Corp", "hash-b", tenant_id=2)

    response = client.get(f"/admin/matters/{tenant_b_matter['id']}", headers=_owner_header(tenant_id=1))
    assert response.status_code == 404

    # Sanity: the SAME owner CAN see their own tenant's Matter.
    own_response = client.get(f"/admin/matters/{tenant_a_matter['id']}", headers=_owner_header(tenant_id=1))
    assert own_response.status_code == 200


def test_list_matters_only_returns_the_callers_own_tenant(client, repo):
    repo.create_matter("Tenant A Corp", "hash-a2", tenant_id=1)
    repo.create_matter("Tenant A Second Matter", "hash-a3", tenant_id=1)
    repo.create_matter("Tenant B Corp", "hash-b2", tenant_id=2)

    tenant_a_names = {
        m["name"] for m in client.get("/admin/matters", headers=_owner_header(tenant_id=1)).json()["matters"]
    }
    tenant_b_names = {
        m["name"] for m in client.get("/admin/matters", headers=_owner_header(tenant_id=2)).json()["matters"]
    }

    assert tenant_a_names == {"Tenant A Corp", "Tenant A Second Matter"}
    assert tenant_b_names == {"Tenant B Corp"}


def test_tenant_b_cannot_create_a_matter_assignment_on_tenant_as_matter(client, repo):
    """Tenant isolation applies before the role check even gets a chance to run - it's a 404, not a 403."""

    tenant_a_matter = repo.create_matter("Tenant A Corp", "hash-a4", tenant_id=1)

    response = client.post(
        f"/admin/matters/{tenant_a_matter['id']}/assignments",
        json={"owner_id": 99, "role": "attorney"},
        headers=_owner_header(tenant_id=2),
    )
    assert response.status_code == 404


def test_documents_are_isolated_per_tenant(client):
    """A category/document created by one tenant is invisible to another tenant's vault listing."""

    create_response = client.post(
        "/categories", json={"name": "TenantASecrets"}, headers=_owner_header(tenant_id=1)
    )
    assert create_response.status_code == 200

    tenant_a_categories = {
        c["name"] for c in client.get("/categories", headers=_owner_header(tenant_id=1)).json()["categories"]
    }
    tenant_b_categories = {
        c["name"] for c in client.get("/categories", headers=_owner_header(tenant_id=2)).json()["categories"]
    }

    assert "TenantASecrets" in tenant_a_categories
    assert "TenantASecrets" not in tenant_b_categories


def test_causes_of_action_library_is_isolated_per_tenant(client):
    """A curated cause of action created by one tenant is invisible to another tenant's library."""

    create_response = client.post(
        "/admin/causes-of-action",
        json={
            "category": "Contracts",
            "name": "Breach of Contract",
            "elements": ["A valid contract existed", "Defendant breached it"],
            "authority_citation": "Restatement (Second) of Contracts § 235",
        },
        headers=_owner_header(tenant_id=1),
    )
    assert create_response.status_code == 200

    tenant_a_names = {
        c["name"] for c in client.get("/admin/causes-of-action", headers=_owner_header(tenant_id=1)).json()["causes_of_action"]
    }
    tenant_b_names = {
        c["name"] for c in client.get("/admin/causes-of-action", headers=_owner_header(tenant_id=2)).json()["causes_of_action"]
    }

    assert "Breach of Contract" in tenant_a_names
    assert "Breach of Contract" not in tenant_b_names


def test_prompt_versions_are_isolated_per_tenant(client):
    """A custom system prompt saved by one tenant does not leak into another tenant's prompt history."""

    create_response = client.post(
        "/admin/prompts/answer_system_prompt",
        json={"text": "Tenant A's custom answer prompt."},
        headers=_owner_header(tenant_id=1),
    )
    assert create_response.status_code == 200

    tenant_a_versions = client.get(
        "/admin/prompts/answer_system_prompt", headers=_owner_header(tenant_id=1)
    ).json()["versions"]
    tenant_b_versions = client.get(
        "/admin/prompts/answer_system_prompt", headers=_owner_header(tenant_id=2)
    ).json()["versions"]

    assert any(v["text"] == "Tenant A's custom answer prompt." for v in tenant_a_versions)
    assert all(v["text"] != "Tenant A's custom answer prompt." for v in tenant_b_versions)


def test_implicit_default_matter_still_works_for_owner_role(client, repo):
    """
    matter_id == 0 (the implicit "Default" matter, no real row - see
    app/security/auth.py's require_end_user_key()) must keep working
    for role='owner' exactly as it did before Step 24, since plenty of
    existing single-Matter-key setups rely on it.
    """

    session = repo.create_intake_session(matter_id=0, title="Intake")
    report = repo.create_report(session["id"], 0, "docx", "c/reports", "r.docx")
    repo.create_report_review(report["id"])

    response = client.post(f"/admin/reports/{report['id']}/approve", headers=_owner_header(tenant_id=1))
    assert response.status_code == 200

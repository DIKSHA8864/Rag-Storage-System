"""
Tests for Owner JWT and End User API-key authentication
(app/security/auth.py) - two separate scopes, two separate secrets,
two separate headers/schemes (Authorization: Bearer <JWT> vs
X-End-User-Key).

Unlike every other test file, these do NOT use the autouse
`_bypass_admin_auth` fixture from conftest.py - they clear both
overrides explicitly so the real dependencies run, since bypassing
auth is exactly what would make these tests meaningless.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import end_user_api, storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key
from app.storage.local_backend import LocalStorageBackend
from config.settings import get_settings


def _owner_bearer_header() -> dict:
    token = create_access_token(owner_id=1, email="owner@example.com")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Undo the autouse bypass from conftest.py for this file only.
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)

    # Same isolation as test_api.py's fixture - nothing here should
    # touch real project storage, even for the one test that
    # actually authenticates successfully and creates a category.
    monkeypatch.setattr(
        storage_api,
        "storage_backend",
        LocalStorageBackend(
            originals_dir=tmp_path / "originals",
            quarantine_dir=tmp_path / "quarantine",
        ),
    )
    monkeypatch.setattr(
        storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db")
    )

    # /end-user/query would otherwise call the real retrieval pipeline
    # (real Postgres/pgvector, real embedding model) - out of scope for
    # an auth test, so it's stubbed to something harmless.
    monkeypatch.setattr(end_user_api, "retrieve", lambda *args, **kwargs: [])

    yield TestClient(storage_api.app)


def test_request_without_bearer_token_is_rejected(client):
    response = client.get("/categories")
    assert response.status_code == 401


def test_request_with_invalid_bearer_token_is_rejected(client):
    response = client.get("/categories", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_request_with_valid_bearer_token_succeeds(client):
    response = client.get("/categories", headers=_owner_bearer_header())
    assert response.status_code == 200


def test_root_endpoint_does_not_require_api_key(client):
    response = client.get("/")
    assert response.status_code == 200


def test_upload_test_page_does_not_require_api_key(client):
    response = client.get("/upload-test")
    assert response.status_code == 200


def test_docs_and_openapi_do_not_require_api_key(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_mutating_endpoints_require_bearer_token(client):
    """Spot-check a representative write endpoint, not just reads."""

    response = client.post("/categories", json={"name": "Contracts"})
    assert response.status_code == 401

    response = client.post(
        "/categories", json={"name": "Contracts"}, headers=_owner_bearer_header()
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------
# Newer admin endpoints (Matters, Retrieval Settings, Prompt Versions) -
# added after the routes above; spot-checked here the same way so
# "protected by require_admin_key" isn't just assumed for them.
# ---------------------------------------------------------------------


def test_matters_endpoints_require_bearer_token(client):
    assert client.get("/admin/matters").status_code == 401
    assert client.post("/admin/matters", json={"name": "Acme Corp"}).status_code == 401

    assert client.get("/admin/matters", headers=_owner_bearer_header()).status_code == 200
    response = client.post(
        "/admin/matters", json={"name": "Acme Corp"}, headers=_owner_bearer_header()
    )
    assert response.status_code == 200


def test_retrieval_settings_endpoints_require_bearer_token(client):
    assert client.get("/admin/retrieval-settings").status_code == 401
    body = {"top_k": 5, "score_threshold": 0.0, "min_chunks": 1}
    assert client.put("/admin/retrieval-settings", json=body).status_code == 401

    assert client.get("/admin/retrieval-settings", headers=_owner_bearer_header()).status_code == 200
    response = client.put(
        "/admin/retrieval-settings", json=body, headers=_owner_bearer_header()
    )
    assert response.status_code == 200


def test_prompt_version_endpoints_require_bearer_token(client):
    name = "narrative_system_prompt"

    assert client.get(f"/admin/prompts/{name}").status_code == 401
    assert client.post(f"/admin/prompts/{name}", json={"text": "New prompt."}).status_code == 401
    assert client.post(f"/admin/prompts/{name}/activate/1").status_code == 401

    assert client.get(f"/admin/prompts/{name}", headers=_owner_bearer_header()).status_code == 200
    created = client.post(
        f"/admin/prompts/{name}", json={"text": "New prompt."}, headers=_owner_bearer_header()
    )
    assert created.status_code == 200

    activated = client.post(
        f"/admin/prompts/{name}/activate/{created.json()['version']}",
        headers=_owner_bearer_header(),
    )
    assert activated.status_code == 200


# ---------------------------------------------------------------------
# End User API key (app/api/end_user_api.py) - a separate scope from
# everything above: different header (X-End-User-Key), different
# secret (END_USER_API_KEY), and - the actual point - neither key
# grants access to the other scope's routes.
# ---------------------------------------------------------------------


def test_end_user_route_without_key_is_rejected(client):
    response = client.post("/end-user/query", json={"query": "hello"})
    assert response.status_code == 401


def test_end_user_route_with_wrong_key_is_rejected(client):
    response = client.post(
        "/end-user/query", json={"query": "hello"}, headers={"X-End-User-Key": "wrong-key"}
    )
    assert response.status_code == 401


def test_end_user_route_with_correct_end_user_key_succeeds(client):
    correct_key = get_settings().end_user_api_key
    response = client.post(
        "/end-user/query", json={"query": "hello"}, headers={"X-End-User-Key": correct_key}
    )
    assert response.status_code == 200


def test_owner_bearer_token_does_not_grant_end_user_access(client):
    """
    The Owner's Bearer token is a real, valid credential - just for
    the wrong scope. Presenting it at an End User route must still
    fail, since that route only ever checks X-End-User-Key.
    """

    response = client.post(
        "/end-user/query", json={"query": "hello"}, headers=_owner_bearer_header()
    )
    assert response.status_code == 401


def test_end_user_key_does_not_grant_admin_access(client):
    """The converse: an End User key must not open any Owner/Admin route."""

    end_user_key = get_settings().end_user_api_key
    response = client.get("/categories", headers={"X-End-User-Key": end_user_key})
    assert response.status_code == 401


def test_owner_bearer_token_as_end_user_key_header_is_rejected(client):
    """Even the Owner's own JWT, sent in the End User's header, must not match."""

    token = _owner_bearer_header()["Authorization"].removeprefix("Bearer ")
    response = client.post(
        "/end-user/query", json={"query": "hello"}, headers={"X-End-User-Key": token}
    )
    assert response.status_code == 401

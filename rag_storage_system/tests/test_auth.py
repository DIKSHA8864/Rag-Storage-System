"""
Tests for admin API-key and End User API-key authentication
(app/security/auth.py) - two separate scopes, two separate secrets,
two separate headers.

Unlike every other test file, these do NOT use the autouse
`_bypass_admin_auth` fixture from conftest.py - they clear both
overrides explicitly so the real dependencies run, since bypassing
auth is exactly what would make these tests meaningless.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import end_user_api, storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key, require_end_user_key
from app.storage.local_backend import LocalStorageBackend
from config.settings import get_settings


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


def test_request_without_api_key_is_rejected(client):
    response = client.get("/categories")
    assert response.status_code == 401


def test_request_with_wrong_api_key_is_rejected(client):
    response = client.get("/categories", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_request_with_correct_api_key_succeeds(client):
    correct_key = get_settings().admin_api_key
    response = client.get("/categories", headers={"X-API-Key": correct_key})
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


def test_mutating_endpoints_require_api_key(client):
    """Spot-check a representative write endpoint, not just reads."""

    response = client.post("/categories", json={"name": "Contracts"})
    assert response.status_code == 401

    correct_key = get_settings().admin_api_key
    response = client.post(
        "/categories", json={"name": "Contracts"}, headers={"X-API-Key": correct_key}
    )
    assert response.status_code == 200


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


def test_admin_key_on_x_api_key_header_does_not_grant_end_user_access(client):
    """
    The admin key is a real, valid credential - just for the wrong
    header/scope. Presenting it as X-API-Key (its own header) at an
    End User route must still fail, since that route only ever checks
    X-End-User-Key.
    """

    admin_key = get_settings().admin_api_key
    response = client.post(
        "/end-user/query", json={"query": "hello"}, headers={"X-API-Key": admin_key}
    )
    assert response.status_code == 401


def test_end_user_key_does_not_grant_admin_access(client):
    """The converse: an End User key must not open any Owner/Admin route."""

    end_user_key = get_settings().end_user_api_key
    response = client.get("/categories", headers={"X-End-User-Key": end_user_key})
    assert response.status_code == 401


def test_admin_key_as_end_user_key_header_is_rejected(client):
    """Even the admin key's own value, sent in the End User's header, must not match."""

    admin_key = get_settings().admin_api_key
    response = client.post(
        "/end-user/query", json={"query": "hello"}, headers={"X-End-User-Key": admin_key}
    )
    assert response.status_code == 401

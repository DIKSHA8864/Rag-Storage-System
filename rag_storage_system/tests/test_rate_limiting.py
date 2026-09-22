"""Tests for rate limiting (app/security/rate_limit.py) - login and Q&A endpoints reject excess requests with 429."""

import pytest
from fastapi.testclient import TestClient

from app.api import auth_api, storage_api
from app.security.auth import create_access_token, require_admin_key, require_end_user_key
from app.security.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client(monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)

    # /auth/login normally hits a real Postgres owners table
    # (app/security/owner_repository.py) - this test only cares about
    # the rate limiter itself, so the owner lookup is stubbed out
    # rather than requiring a real database in every environment.
    monkeypatch.setattr(auth_api, "get_owner_by_email", lambda email: None)

    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def test_login_is_rate_limited_after_five_attempts_per_minute(client):
    for _ in range(5):
        client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong"})

    response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert response.status_code == 429
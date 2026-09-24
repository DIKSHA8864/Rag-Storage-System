"""
Phase 5 Step 25 - Billing/Subscription foundation
(app/billing/, app/api/billing_api.py, and the plan-limit enforcement
wired into app/api/storage_api.py / app/api/end_user_api.py).

Two fixture styles, same as tests/test_api.py and
tests/test_multi_tenancy.py: `client` bypasses auth (default owner,
tenant_id=1 - the seeded Default Organization, which starts on the
seeded unlimited plan) for enforcement tests that need full control
over exactly which plan/subscription is active; `_owner_header()`
issues a real JWT for the role-gating and cross-tenant tests, where
bypassing auth would make the assertion meaningless.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.billing.service import BillingService, PlanLimitExceededError, RESOURCE_LLM_CALLS
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key
from app.storage.local_backend import LocalStorageBackend


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(tmp_path, repo, monkeypatch):
    backend = LocalStorageBackend(
        originals_dir=tmp_path / "originals",
        quarantine_dir=tmp_path / "quarantine",
    )
    monkeypatch.setattr(storage_api, "storage_backend", backend)
    monkeypatch.setattr(storage_api, "metadata_repository", repo)

    return TestClient(storage_api.app)


@pytest.fixture
def auth_client(repo, monkeypatch):
    """Same repo, but with real JWT auth (not bypassed) - for role-gating and cross-tenant tests."""

    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", repo)

    yield TestClient(storage_api.app)

    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def _owner_header(tenant_id: int = 1, role: str = "owner", owner_id: int = 1) -> dict:
    token = create_access_token(owner_id=owner_id, email=f"owner-{tenant_id}@example.com", tenant_id=tenant_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _make_limited_plan(repo, **limits) -> dict:
    return repo.create_plan(slug="limited", name="Limited Plan", **limits)


# ---------------------------------------------------------------------
# Repository-level: plans + tenant_subscriptions
# ---------------------------------------------------------------------


def test_default_organization_is_seeded_with_an_unlimited_plan_and_active_subscription(repo):
    subscription = repo.get_subscription_for_tenant(1)
    assert subscription is not None
    assert subscription["status"] == "active"

    plan = repo.get_plan(subscription["plan_id"])
    assert plan["slug"] == "default-unlimited"
    assert plan["max_matters"] is None
    assert plan["max_documents"] is None
    assert plan["max_storage_bytes"] is None
    assert plan["max_llm_calls_per_month"] is None


def test_create_plan_and_look_it_up_by_slug(repo):
    plan = repo.create_plan(
        slug="starter", name="Starter", max_matters=5, max_documents=100,
        max_storage_bytes=10_000_000, max_llm_calls_per_month=500,
    )
    assert plan["slug"] == "starter"

    fetched = repo.get_plan_by_slug("starter")
    assert fetched["id"] == plan["id"]
    assert fetched["max_matters"] == 5


def test_a_tenant_with_no_subscription_row_has_none(repo):
    assert repo.get_subscription_for_tenant(42) is None


def test_change_tenant_plan_moves_an_existing_subscription(repo):
    plan_a = repo.create_plan(slug="a", name="A")
    plan_b = repo.create_plan(slug="b", name="B")
    repo.create_tenant_subscription(
        99, plan_a["id"], status="active", current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2025-02-01T00:00:00+00:00",
    )

    updated = repo.change_tenant_plan(
        99, plan_b["id"], current_period_start="2025-02-01T00:00:00+00:00",
        current_period_end="2025-03-01T00:00:00+00:00",
    )
    assert updated["plan_id"] == plan_b["id"]
    assert updated["status"] == "active"


def test_update_subscription_status_can_cancel(repo):
    plan = repo.create_plan(slug="c", name="C")
    repo.create_tenant_subscription(
        7, plan["id"], status="active", current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2025-02-01T00:00:00+00:00",
    )

    canceled = repo.update_subscription_status(7, "canceled", canceled_at="2025-01-15T00:00:00+00:00")
    assert canceled["status"] == "canceled"
    assert canceled["canceled_at"] is not None


def test_get_tenant_resource_usage_counts_matters_and_documents(repo):
    repo.create_matter("Matter One", "hash-1", tenant_id=55)
    repo.create_matter("Matter Two", "hash-2", tenant_id=55)

    usage = repo.get_tenant_resource_usage(55)
    assert usage["matters"] == 2
    assert usage["documents"] == 0
    assert usage["storage_bytes"] == 0


def test_count_llm_usage_since_only_counts_this_tenants_rows(repo):
    repo.add_llm_usage_log(
        matter_id=None, intake_session_id=None, purpose="end_user_query", model="template",
        input_tokens=0, output_tokens=0, latency_ms=1, tenant_id=1,
    )
    repo.add_llm_usage_log(
        matter_id=None, intake_session_id=None, purpose="end_user_query", model="template",
        input_tokens=0, output_tokens=0, latency_ms=1, tenant_id=2,
    )

    assert repo.count_llm_usage_since(1, "2000-01-01T00:00:00+00:00") == 1
    assert repo.count_llm_usage_since(2, "2000-01-01T00:00:00+00:00") == 1
    assert repo.count_llm_usage_since(3, "2000-01-01T00:00:00+00:00") == 0


# ---------------------------------------------------------------------
# BillingService
# ---------------------------------------------------------------------


def test_check_limit_fails_open_when_tenant_has_no_subscription(repo):
    service = BillingService(repo)
    service.check_limit(999, RESOURCE_LLM_CALLS)  # must not raise


def test_check_limit_fails_open_when_plans_limit_is_none(repo):
    plan = repo.create_plan(slug="unlimited-llm", name="Unlimited LLM")  # every limit column NULL
    repo.create_tenant_subscription(
        21, plan["id"], status="active", current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2025-02-01T00:00:00+00:00",
    )

    BillingService(repo).check_limit(21, RESOURCE_LLM_CALLS)  # must not raise


def test_check_limit_raises_once_the_limit_would_be_exceeded(repo):
    plan = _make_limited_plan(repo, max_matters=1)
    repo.create_tenant_subscription(
        33, plan["id"], status="active", current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2025-02-01T00:00:00+00:00",
    )
    service = BillingService(repo)

    service.check_limit(33, "matters")  # 0 existing + 1 requested == limit of 1 -> fine
    repo.create_matter("First Matter", "hash-x", tenant_id=33)

    with pytest.raises(PlanLimitExceededError):
        service.check_limit(33, "matters")  # 1 existing + 1 requested > limit of 1


def test_subscribe_creates_a_subscription_then_change_plan_moves_it(repo):
    repo.create_plan(slug="starter", name="Starter", max_matters=3)
    repo.create_plan(slug="pro", name="Pro", max_matters=50)
    service = BillingService(repo)

    service.subscribe(66, "starter")
    subscription = service.get_subscription(66)
    assert subscription["plan"]["slug"] == "starter"

    service.change_plan(66, "pro")
    subscription = service.get_subscription(66)
    assert subscription["plan"]["slug"] == "pro"


def test_cancel_sets_status_to_canceled(repo):
    repo.create_plan(slug="starter2", name="Starter 2")
    service = BillingService(repo)
    service.subscribe(77, "starter2")

    canceled = service.cancel(77)
    assert canceled["status"] == "canceled"


# ---------------------------------------------------------------------
# API: plan catalog + subscription management
# ---------------------------------------------------------------------


def test_default_plan_is_visible_in_the_plan_catalog(client):
    response = client.get("/admin/billing/plans")
    assert response.status_code == 200
    slugs = {p["slug"] for p in response.json()["plans"]}
    assert "default-unlimited" in slugs


def test_owner_can_create_a_plan(client):
    response = client.post(
        "/admin/billing/plans",
        json={"slug": "pro", "name": "Pro", "max_matters": 10, "max_documents": 1000},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "pro"
    assert body["max_matters"] == 10
    assert body["max_documents"] == 1000
    assert body["max_llm_calls_per_month"] is None


def test_attorney_role_cannot_create_a_plan(auth_client):
    response = auth_client.post(
        "/admin/billing/plans",
        json={"slug": "pro2", "name": "Pro 2"},
        headers=_owner_header(tenant_id=1, role="attorney"),
    )
    assert response.status_code == 403


def test_owner_can_subscribe_their_tenant_to_a_plan_and_read_it_back(client):
    client.post("/admin/billing/plans", json={"slug": "growth", "name": "Growth", "max_matters": 20})

    subscribe_response = client.post("/admin/billing/subscription", json={"plan_slug": "growth"})
    assert subscribe_response.status_code == 200
    assert subscribe_response.json()["plan"]["slug"] == "growth"

    get_response = client.get("/admin/billing/subscription")
    assert get_response.status_code == 200
    assert get_response.json()["plan"]["slug"] == "growth"
    assert get_response.json()["status"] == "active"


def test_usage_endpoint_reports_current_counts_and_limits(client):
    client.post("/admin/billing/plans", json={"slug": "usage-plan", "name": "Usage Plan", "max_matters": 5})
    client.post("/admin/billing/subscription", json={"plan_slug": "usage-plan"})

    client.post("/admin/matters", json={"name": "A Matter"})

    response = client.get("/admin/billing/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["matters"] == 1
    assert body["limits"]["max_matters"] == 5


def test_subscription_and_usage_are_isolated_per_tenant(auth_client, repo):
    repo.create_plan(slug="tenant-a-plan", name="Tenant A Plan", max_matters=2)
    repo.create_plan(slug="tenant-b-plan", name="Tenant B Plan", max_matters=9)

    auth_client.post(
        "/admin/billing/subscription", json={"plan_slug": "tenant-a-plan"}, headers=_owner_header(tenant_id=10)
    )
    auth_client.post(
        "/admin/billing/subscription", json={"plan_slug": "tenant-b-plan"}, headers=_owner_header(tenant_id=20)
    )

    tenant_a_sub = auth_client.get("/admin/billing/subscription", headers=_owner_header(tenant_id=10)).json()
    tenant_b_sub = auth_client.get("/admin/billing/subscription", headers=_owner_header(tenant_id=20)).json()

    assert tenant_a_sub["plan"]["slug"] == "tenant-a-plan"
    assert tenant_b_sub["plan"]["slug"] == "tenant-b-plan"


# ---------------------------------------------------------------------
# Backend enforcement (never just the frontend)
# ---------------------------------------------------------------------


def test_creating_a_matter_beyond_the_plan_limit_is_rejected_with_402(client, repo):
    plan = _make_limited_plan(repo, max_matters=1)
    repo.change_tenant_plan(
        1, plan["id"], current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2099-01-01T00:00:00+00:00",
    )

    first = client.post("/admin/matters", json={"name": "Matter One"})
    assert first.status_code == 200

    second = client.post("/admin/matters", json={"name": "Matter Two"})
    assert second.status_code == 402


def test_uploading_a_document_beyond_the_plan_document_limit_is_rejected_with_402(client, repo):
    plan = _make_limited_plan(repo, max_documents=1)
    repo.change_tenant_plan(
        1, plan["id"], current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2099-01-01T00:00:00+00:00",
    )
    client.post("/categories", json={"name": "Docs"})

    first = client.post(
        "/categories/Docs/documents", files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}
    )
    assert first.status_code == 200

    second = client.post(
        "/categories/Docs/documents", files={"file": ("b.txt", io.BytesIO(b"world"), "text/plain")}
    )
    assert second.status_code == 402


def test_uploading_a_document_beyond_the_plan_storage_limit_is_rejected_with_402(client, repo):
    plan = _make_limited_plan(repo, max_storage_bytes=3)
    repo.change_tenant_plan(
        1, plan["id"], current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2099-01-01T00:00:00+00:00",
    )
    client.post("/categories", json={"name": "Docs"})

    response = client.post(
        "/categories/Docs/documents", files={"file": ("big.txt", io.BytesIO(b"way too big"), "text/plain")}
    )
    assert response.status_code == 402


def test_research_ask_beyond_the_monthly_llm_call_limit_is_rejected_with_402(client, repo, monkeypatch):
    plan = _make_limited_plan(repo, max_llm_calls_per_month=1)
    repo.change_tenant_plan(
        1, plan["id"], current_period_start="2025-01-01T00:00:00+00:00",
        current_period_end="2099-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(storage_api, "retrieve", lambda *args, **kwargs: [])

    first = client.post("/research/ask", json={"query": "What does the contract say?"})
    assert first.status_code == 200

    second = client.post("/research/ask", json={"query": "Another question."})
    assert second.status_code == 402


def test_matters_stay_unrestricted_for_a_tenant_with_no_subscription_at_all(auth_client):
    """A tenant that was never put on billing (no subscription row at all) is never blocked - fail-open, see BillingService.check_limit()."""

    response = auth_client.post(
        "/admin/matters", json={"name": "Unbilled Tenant's Matter"}, headers=_owner_header(tenant_id=123)
    )
    assert response.status_code == 200

"""
Stripe billing (BILLING_PROVIDER=stripe): Checkout and the Billing Portal
against a fake Stripe HTTP API, webhook signature checks, and the rule that
a paid plan is granted only by a verified Stripe event - never by a click.
"""

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.billing as billing
from app.api import storage_api
from app.billing.stripe_provider import (
    StripeClient,
    StripePaymentProvider,
    WebhookSignatureError,
    _flatten,
    verify_webhook,
)
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key
from config.settings import get_settings

SECRET = "whsec_test"
NOW = int(time.time())


class FakeStripe:
    """Answers the handful of Stripe endpoints we call; records every request."""

    def __init__(self):
        self.calls = []
        self.subscriptions = {}

    def request(self, method, url, data=None, headers=None, timeout=None):
        path = url.replace("https://api.stripe.com", "")
        form = dict(data or [])
        self.calls.append((method, path, form, headers))
        if (method, path) == ("POST", "/v1/checkout/sessions"):
            return self._ok({"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"})
        if (method, path) == ("POST", "/v1/billing_portal/sessions"):
            return self._ok({"url": "https://billing.stripe.com/p/session/1"})
        if path.startswith("/v1/subscriptions/"):
            sub_id = path.rsplit("/", 1)[1]
            if sub_id not in self.subscriptions:
                return self._error(404, "No such subscription")
            if method == "DELETE":
                self.subscriptions[sub_id]["status"] = "canceled"
            return self._ok(self.subscriptions[sub_id])
        return self._error(404, "Unknown endpoint")

    @staticmethod
    def _ok(body):
        return SimpleNamespace(status_code=200, json=lambda: body)

    @staticmethod
    def _error(status, message):
        return SimpleNamespace(status_code=status, json=lambda: {"error": {"message": message}})

    def add_subscription(self, sub_id, price, status="active", tenant_id=1, customer="cus_1"):
        self.subscriptions[sub_id] = {
            "id": sub_id, "status": status, "customer": customer, "metadata": {"tenant_id": str(tenant_id)},
            "canceled_at": None,
            "items": {"data": [{"id": f"si_{sub_id}", "price": {"id": price},
                                "current_period_start": NOW, "current_period_end": NOW + 30 * 86400}]},
        }


@pytest.fixture
def repo(tmp_path):
    repo = SQLiteMetadataRepository(tmp_path / "metadata.db")
    pro = repo.create_plan(slug="pro", name="Pro", price_cents=9900, max_matters=500)
    repo.set_plan_provider_price(pro["id"], "price_pro")
    team = repo.create_plan(slug="team", name="Team", price_cents=19900)
    repo.set_plan_provider_price(team["id"], "price_team")
    repo.create_plan(slug="free", name="Free", price_cents=0, max_matters=3)
    return repo


@pytest.fixture
def stripe(monkeypatch, repo):
    fake = FakeStripe()
    settings = get_settings()
    monkeypatch.setattr(settings, "billing_provider", "stripe")
    monkeypatch.setattr(settings, "stripe_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "stripe_fallback_plan_slug", "")
    monkeypatch.setattr(settings, "billing_plan_admin_emails", "")
    monkeypatch.setattr(settings, "frontend_base_url", "https://app.example.com")
    monkeypatch.setattr(billing, "_provider_instance", StripePaymentProvider(StripeClient("sk_test_1", session=fake)))
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    return fake


@pytest.fixture
def client(stripe):
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _signed(event: dict, secret: str = SECRET, timestamp: int | None = None) -> tuple[bytes, str]:
    payload = json.dumps(event).encode()
    timestamp = timestamp or int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={signature}"


def _post_event(client, event, **kwargs):
    payload, header = _signed(event, **kwargs)
    return client.post("/billing/stripe/webhook", content=payload, headers={"Stripe-Signature": header})


def _checkout_completed(sub_id="sub_1", tenant_id=1, payment_status="paid", event_id="evt_1"):
    return {"id": event_id, "type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "payment_status": payment_status, "client_reference_id": str(tenant_id),
        "subscription": sub_id, "metadata": {"tenant_id": str(tenant_id), "plan_slug": "pro"},
    }}}


def _plan_of(repo, tenant_id=1):
    subscription = repo.get_subscription_for_tenant(tenant_id)
    return repo.get_plan(subscription["plan_id"])["slug"], subscription


# ----------------------------------------------------------------------
# Signatures and encoding
# ----------------------------------------------------------------------

def test_webhook_signature_verification():
    payload, header = _signed({"id": "evt"})
    assert verify_webhook(payload, header, SECRET)["id"] == "evt"
    for bad_payload, bad_header, secret in [
        (payload, header, "whsec_other"),
        (payload + b" ", header, SECRET),
        (payload, None, SECRET),
        (payload, "t=abc,v1=00", SECRET),
        (payload, header, ""),
    ]:
        with pytest.raises(WebhookSignatureError):
            verify_webhook(bad_payload, bad_header, secret)
    old_payload, old_header = _signed({"id": "evt"}, timestamp=int(time.time()) - 3600)
    with pytest.raises(WebhookSignatureError, match="too old"):
        verify_webhook(old_payload, old_header, SECRET)


def test_stripe_form_encoding():
    assert _flatten({"line_items": [{"price": "p", "quantity": 1}], "metadata": {"a": 1}, "skip": None, "x": True}) == [
        ("line_items[0][price]", "p"), ("line_items[0][quantity]", "1"), ("metadata[a]", "1"), ("x", "true"),
    ]


# ----------------------------------------------------------------------
# Checkout: nothing is granted until Stripe says so
# ----------------------------------------------------------------------

def test_checkout_returns_the_stripe_page_and_changes_nothing(client, repo, stripe):
    before = _plan_of(repo)[0]

    response = client.post("/admin/billing/checkout", json={"plan_slug": "pro"})

    assert response.json() == {"url": "https://checkout.stripe.com/c/pay/cs_1"}
    method, path, form, headers = stripe.calls[-1]
    assert (method, path) == ("POST", "/v1/checkout/sessions")
    assert form["line_items[0][price]"] == "price_pro" and form["client_reference_id"] == "1"
    assert form["subscription_data[metadata][tenant_id]"] == "1"
    assert form["success_url"] == "https://app.example.com/billing?checkout=success"
    assert form["customer_email"] == "test-owner@example.com"
    assert headers["Authorization"] == "Bearer sk_test_1"
    assert _plan_of(repo)[0] == before


def test_checkout_refusals(client, repo, monkeypatch):
    assert client.post("/admin/billing/checkout", json={"plan_slug": "free"}).status_code == 400
    assert client.post("/admin/billing/checkout", json={"plan_slug": "nope"}).status_code == 404
    unpriced = repo.create_plan(slug="gold", name="Gold", price_cents=500)
    assert unpriced and client.post("/admin/billing/checkout", json={"plan_slug": "gold"}).status_code == 502
    monkeypatch.setattr(get_settings(), "billing_provider", "manual")
    assert client.post("/admin/billing/checkout", json={"plan_slug": "pro"}).status_code == 409


def test_a_paid_plan_cannot_be_assigned_without_paying(client, repo):
    assert client.post("/admin/billing/subscription", json={"plan_slug": "pro"}).status_code == 409
    assert client.put("/admin/billing/subscription", json={"plan_slug": "pro"}).status_code == 409
    assert client.post("/admin/billing/subscription", json={"plan_slug": "free"}).status_code == 200
    assert _plan_of(repo)[0] == "free"


# ----------------------------------------------------------------------
# Webhooks
# ----------------------------------------------------------------------

def test_paid_checkout_webhook_grants_the_plan_from_stripes_own_record(client, repo, stripe):
    stripe.add_subscription("sub_1", "price_pro")

    response = _post_event(client, _checkout_completed())

    assert response.json() == {"received": True, "outcome": "synced_active"}
    slug, subscription = _plan_of(repo)
    assert (slug, subscription["status"], subscription["provider"]) == ("pro", "active", "stripe")
    assert (subscription["provider_customer_id"], subscription["provider_subscription_id"]) == ("cus_1", "sub_1")
    assert str(subscription["current_period_end"]).startswith(
        time.strftime("%Y-%m-%d", time.gmtime(NOW + 30 * 86400)))
    assert _post_event(client, _checkout_completed()).status_code == 200  # a retried delivery changes nothing
    assert _plan_of(repo)[0] == "pro"


def test_bad_signature_and_unpaid_checkout_grant_nothing(client, repo, stripe):
    stripe.add_subscription("sub_1", "price_pro")
    payload, header = _signed(_checkout_completed(), secret="whsec_attacker")
    assert client.post("/billing/stripe/webhook", content=payload, headers={"Stripe-Signature": header}).status_code == 400
    assert _post_event(client, _checkout_completed(payment_status="unpaid")).json()["outcome"] == "awaiting_payment"
    stripe.add_subscription("sub_2", "price_pro", status="incomplete")
    assert _post_event(client, _checkout_completed(sub_id="sub_2")).json()["outcome"] == "not_granted_incomplete"
    stripe.add_subscription("sub_3", "price_unknown")
    assert _post_event(client, _checkout_completed(sub_id="sub_3")).json()["outcome"] == "unknown_price"
    assert _plan_of(repo)[0] == "default-unlimited"


def test_subscription_updates_follow_stripe(client, repo, stripe):
    stripe.add_subscription("sub_1", "price_pro")
    _post_event(client, _checkout_completed())

    stripe.subscriptions["sub_1"]["status"] = "past_due"
    stripe.subscriptions["sub_1"]["items"]["data"][0]["price"]["id"] = "price_team"
    event = {"id": "evt_2", "type": "customer.subscription.updated", "data": {"object": {"id": "sub_1", "status": "active"}}}
    assert _post_event(client, event).json()["outcome"] == "synced_past_due"  # Stripe's current state wins over the event body
    slug, subscription = _plan_of(repo)
    assert (slug, subscription["status"]) == ("team", "past_due")

    invoice = {"id": "evt_3", "type": "invoice.paid", "data": {"object": {"parent": {"subscription_details": {"subscription": "sub_1"}}}}}
    stripe.subscriptions["sub_1"]["status"] = "active"
    assert _post_event(client, invoice).json()["outcome"] == "synced_active"


def test_ending_a_subscription(client, repo, stripe, monkeypatch):
    stripe.add_subscription("sub_1", "price_pro")
    _post_event(client, _checkout_completed())
    deleted = {"id": "evt_9", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_1"}}}

    stripe.subscriptions["sub_1"]["status"] = "canceled"
    assert _post_event(client, deleted).json()["outcome"] == "ended"
    slug, subscription = _plan_of(repo)
    assert (slug, subscription["status"]) == ("pro", "canceled")

    monkeypatch.setattr(get_settings(), "stripe_fallback_plan_slug", "free")
    _post_event(client, deleted)
    slug, subscription = _plan_of(repo)
    assert (slug, subscription["status"], subscription["provider_subscription_id"]) == ("free", "active", None)


def test_an_old_subscription_ending_leaves_the_new_one_alone(client, repo, stripe):
    stripe.add_subscription("sub_old", "price_pro")
    stripe.add_subscription("sub_new", "price_team")
    _post_event(client, _checkout_completed(sub_id="sub_new"))
    stripe.subscriptions["sub_old"]["status"] = "canceled"

    event = {"id": "evt_old", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_old"}}}
    assert _post_event(client, event).json()["outcome"] == "ended_not_current"
    assert _plan_of(repo)[0] == "team"


def test_a_subscription_cannot_move_between_organizations(client, repo, stripe):
    stripe.add_subscription("sub_1", "price_pro", tenant_id=1)
    with repo._connect() as conn:
        conn.execute("INSERT OR IGNORE INTO tenants (id, name, slug, created_at) VALUES (2, 'Two', 'two', '2026-01-01')")
    assert _post_event(client, _checkout_completed(tenant_id=2)).json()["outcome"] == "tenant_conflict"
    assert repo.get_subscription_for_tenant(2) is None


def test_webhook_is_off_without_stripe(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_provider", "manual")
    assert _post_event(client, _checkout_completed()).status_code == 404


# ----------------------------------------------------------------------
# Owner actions on an existing Stripe subscription
# ----------------------------------------------------------------------

def test_portal_change_and_cancel_go_through_stripe(client, repo, stripe):
    assert client.post("/admin/billing/portal").status_code == 404
    stripe.add_subscription("sub_1", "price_pro")
    _post_event(client, _checkout_completed())

    assert client.post("/admin/billing/portal").json()["url"].startswith("https://billing.stripe.com/")
    assert client.post("/admin/billing/checkout", json={"plan_slug": "team"}).status_code == 409  # already paying

    assert client.put("/admin/billing/subscription", json={"plan_slug": "team"}).status_code == 200
    method, path, form, _ = stripe.calls[-1]
    assert (method, path, form["items[0][id]"], form["items[0][price]"]) == ("POST", "/v1/subscriptions/sub_1", "si_sub_1", "price_team")

    assert client.post("/admin/billing/subscription/cancel").status_code == 200
    assert stripe.calls[-1][:2] == ("DELETE", "/v1/subscriptions/sub_1")

    info = client.get("/admin/billing/provider").json()
    assert (info["provider"], info["checkout_enabled"], info["can_manage_billing"]) == ("stripe", True, True)


def test_only_plan_admins_create_or_price_plans_with_stripe_on(client, repo, monkeypatch):
    plan = {"slug": "cheap", "name": "Cheap", "price_cents": 0}
    assert client.post("/admin/billing/plans", json=plan).status_code == 403
    assert client.get("/admin/billing/provider").json()["can_manage_plans"] is False

    monkeypatch.setattr(get_settings(), "billing_plan_admin_emails", "test-owner@example.com")
    created = client.post("/admin/billing/plans", json={**plan, "price_cents": 1500, "provider_price_id": "price_cheap"})
    assert created.status_code == 200 and created.json()["provider_price_id"] == "price_cheap"
    plan_id = created.json()["id"]
    assert client.put(f"/admin/billing/plans/{plan_id}/provider-price", json={"provider_price_id": "prod_x"}).status_code == 400
    assert client.put(f"/admin/billing/plans/{plan_id}/provider-price", json={"provider_price_id": None}).json()["provider_price_id"] is None

    monkeypatch.setattr(get_settings(), "billing_plan_admin_emails", "someone-else@example.com")
    assert client.put(f"/admin/billing/plans/{plan_id}/provider-price", json={"provider_price_id": "price_y"}).status_code == 403

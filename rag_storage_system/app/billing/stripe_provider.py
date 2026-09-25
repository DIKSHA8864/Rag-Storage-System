"""
Stripe as the payment provider (BILLING_PROVIDER=stripe).

How a paid plan starts: the owner is sent to a Stripe Checkout page
(create_checkout_session). Nothing changes on our side until Stripe
itself tells us, through a signed webhook (app/billing/stripe_webhooks.py),
that the subscription exists and is paid. A plan is never marked paid
because a button was clicked. Card details never touch this server - they
stay on Stripe's pages (Checkout and the Billing Portal).

Talks to Stripe's HTTP API with `requests` (form-encoded, as Stripe's API
expects) and verifies webhook signatures with the documented HMAC-SHA256
scheme, so there is no SDK dependency to keep in step.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import requests

from app.billing.provider import PaymentProvider, ProviderSubscriptionResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.stripe.com"
WEBHOOK_TOLERANCE_SECONDS = 300


class StripeError(Exception):
    """Stripe refused or couldn't be reached - the message is safe to show an owner."""


class CheckoutRequired(Exception):
    """A paid plan can only start or be switched to through Stripe Checkout, never by assignment."""


class WebhookSignatureError(Exception):
    pass


def _flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """{"a": {"b": 1}, "c": [{"d": 2}]} -> [("a[b]", "1"), ("c[0][d]", "2")] - Stripe's form encoding."""

    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            pairs += _flatten(value, name)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    pairs += _flatten(item, f"{name}[{index}]")
                else:
                    pairs.append((f"{name}[{index}]", str(item)))
        elif isinstance(value, bool):
            pairs.append((name, "true" if value else "false"))
        else:
            pairs.append((name, str(value)))
    return pairs


class StripeClient:
    def __init__(self, secret_key: str, session: Optional[requests.Session] = None, timeout: float = 30,
                 api_base: str = API_BASE):
        if not secret_key:
            raise StripeError("STRIPE_SECRET_KEY is not set.")
        self._key = secret_key
        self._api_base = (api_base or API_BASE).rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    def request(self, method: str, path: str, data: Optional[dict] = None, idempotency_key: Optional[str] = None) -> dict:
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self._session.request(
                method, f"{self._api_base}{path}", data=_flatten(data or {}), headers=headers, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise StripeError("Stripe could not be reached - try again.") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            message = (body.get("error") or {}).get("message") or f"HTTP {response.status_code}"
            logger.warning("Stripe %s %s failed: %s", method, path, message)
            raise StripeError(f"Stripe: {message}")
        return body


class StripePaymentProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, client: StripeClient):
        self.client = client

    # --- PaymentProvider (used by BillingService's owner-facing actions) ---

    def start_subscription(self, tenant_id: int, plan: dict) -> ProviderSubscriptionResult:
        if int(plan.get("price_cents") or 0) > 0:
            raise CheckoutRequired("Paid plans start through Stripe Checkout (Billing -> Subscribe).")
        return ProviderSubscriptionResult()

    def change_subscription(self, tenant_id: int, provider_subscription_id: Optional[str], new_plan: dict) -> ProviderSubscriptionResult:
        paid = int(new_plan.get("price_cents") or 0) > 0
        if not provider_subscription_id:
            if paid:
                raise CheckoutRequired("Start the paid plan through Stripe Checkout (Billing -> Subscribe).")
            return ProviderSubscriptionResult()
        if not paid:
            # Moving to a free plan ends the paid Stripe subscription.
            self.cancel_subscription(tenant_id, provider_subscription_id)
            return ProviderSubscriptionResult()
        if not new_plan.get("provider_price_id"):
            raise StripeError(f"The plan '{new_plan['slug']}' has no Stripe price set.")
        subscription = self.client.request("GET", f"/v1/subscriptions/{provider_subscription_id}")
        item_id = subscription["items"]["data"][0]["id"]
        self.client.request(
            "POST", f"/v1/subscriptions/{provider_subscription_id}",
            {"items": [{"id": item_id, "price": new_plan["provider_price_id"]}], "proration_behavior": "create_prorations",
             "metadata": {"tenant_id": tenant_id, "plan_slug": new_plan["slug"]}},
        )
        return ProviderSubscriptionResult(provider=self.name, provider_subscription_id=provider_subscription_id)

    def cancel_subscription(self, tenant_id: int, provider_subscription_id: Optional[str]) -> None:
        if provider_subscription_id:
            self.client.request("DELETE", f"/v1/subscriptions/{provider_subscription_id}")

    # --- Stripe-hosted pages ---

    def create_checkout_session(self, tenant_id: int, plan: dict, customer_id: Optional[str], email: Optional[str],
                                success_url: str, cancel_url: str) -> str:
        if not plan.get("provider_price_id"):
            raise StripeError(f"The plan '{plan['name']}' has no Stripe price set - ask the platform admin.")
        data = {
            "mode": "subscription",
            "line_items": [{"price": plan["provider_price_id"], "quantity": 1}],
            "client_reference_id": tenant_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"tenant_id": tenant_id, "plan_slug": plan["slug"]},
            "subscription_data": {"metadata": {"tenant_id": tenant_id, "plan_slug": plan["slug"]}},
        }
        if customer_id:
            data["customer"] = customer_id
        elif email:
            data["customer_email"] = email
        session = self.client.request("POST", "/v1/checkout/sessions", data)
        return session["url"]

    def create_portal_session(self, customer_id: str, return_url: str) -> str:
        session = self.client.request("POST", "/v1/billing_portal/sessions", {"customer": customer_id, "return_url": return_url})
        return session["url"]

    def retrieve_subscription(self, subscription_id: str) -> dict:
        return self.client.request("GET", f"/v1/subscriptions/{subscription_id}")


def verify_webhook(payload: bytes, signature_header: Optional[str], secret: str, now: Optional[float] = None) -> dict:
    """
    Stripe's documented scheme: header "t=<unix time>,v1=<hex HMAC-SHA256 of '<t>.<payload>'>" signed with the
    endpoint's signing secret. Rejects a bad signature or one older than WEBHOOK_TOLERANCE_SECONDS (replays).
    """

    if not secret:
        raise WebhookSignatureError("STRIPE_WEBHOOK_SECRET is not set.")
    if not signature_header:
        raise WebhookSignatureError("Missing Stripe-Signature header.")
    parts = [part.split("=", 1) for part in signature_header.split(",") if "=" in part]
    timestamps = [value for key, value in parts if key == "t"]
    signatures = [value for key, value in parts if key == "v1"]
    if not timestamps or not signatures:
        raise WebhookSignatureError("Malformed Stripe-Signature header.")
    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise WebhookSignatureError("Malformed Stripe-Signature timestamp.") from exc

    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise WebhookSignatureError("Signature does not match.")
    if abs((now if now is not None else time.time()) - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        raise WebhookSignatureError("Signature is too old.")
    try:
        return json.loads(payload)
    except ValueError as exc:
        raise WebhookSignatureError("Payload is not JSON.") from exc

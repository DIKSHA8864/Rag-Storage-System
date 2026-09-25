"""
Applies Stripe webhook events to our subscription records - the only way
a paid plan is ever granted, changed or ended under BILLING_PROVIDER=stripe.

Every event is handled the same way: find the Stripe subscription it is
about, fetch that subscription's current state from Stripe (so a late or
out-of-order delivery can never roll it back), and write exactly that to
the tenant's row. Nothing is inferred from the event body beyond which
subscription to look at, and the event itself was already verified as
signed by Stripe (stripe_provider.verify_webhook).

- The tenant is the one our own Checkout session named (client_reference_id
  / metadata we set), or the tenant already holding that subscription.
- The plan is the one whose provider_price_id is the subscription's price.
  An unknown price is refused, never guessed.
- A subscription that is not paid yet ("incomplete") grants nothing.
- When a subscription ends (canceled / expired / unpaid), the tenant moves
  to STRIPE_FALLBACK_PLAN_SLUG if one is set (so the paid limits end with
  the payments); otherwise the row is marked canceled on its plan.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

_GRANTING = {"active": "active", "trialing": "trialing", "past_due": "past_due"}
_ENDED = {"canceled", "incomplete_expired", "unpaid"}

HANDLED_EVENTS = {
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted",
    "invoice.paid", "invoice.payment_failed",
}


def _iso(epoch: Optional[int]) -> Optional[str]:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat() if epoch else None


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _invoice_subscription_id(invoice: dict) -> Optional[str]:
    if invoice.get("subscription"):
        return invoice["subscription"]
    details = ((invoice.get("parent") or {}).get("subscription_details") or {})  # newer API versions
    return details.get("subscription")


def handle_event(event: dict, repo, provider) -> str:
    """Apply one verified event. Returns a short outcome for the log/response."""

    event_type = event.get("type", "")
    if event_type not in HANDLED_EVENTS:
        return "ignored"
    obj = (event.get("data") or {}).get("object") or {}

    tenant_hint = None
    if event_type.startswith("checkout.session."):
        if obj.get("mode") != "subscription":
            return "ignored"
        if obj.get("payment_status") not in ("paid", "no_payment_required"):
            return "awaiting_payment"
        tenant_hint = _int(obj.get("client_reference_id")) or _int((obj.get("metadata") or {}).get("tenant_id"))
        subscription_id = obj.get("subscription")
    elif event_type.startswith("customer.subscription."):
        subscription_id = obj.get("id")
    else:
        subscription_id = _invoice_subscription_id(obj)

    if not subscription_id:
        return "no_subscription"
    return sync_subscription(subscription_id, repo, provider, tenant_hint)


def sync_subscription(subscription_id: str, repo, provider, tenant_hint: Optional[int] = None) -> str:
    subscription = provider.retrieve_subscription(subscription_id)

    existing = repo.get_subscription_by_provider_id(subscription_id)
    metadata_tenant = _int((subscription.get("metadata") or {}).get("tenant_id"))
    tenant_id = tenant_hint or metadata_tenant or (existing["tenant_id"] if existing else None)
    if tenant_id is None:
        logger.warning("Stripe subscription %s has no tenant - ignored.", subscription_id)
        return "unmatched"
    if (metadata_tenant and metadata_tenant != tenant_id) or (existing and existing["tenant_id"] != tenant_id):
        logger.error("Stripe subscription %s names conflicting tenants - ignored.", subscription_id)
        return "tenant_conflict"

    items = ((subscription.get("items") or {}).get("data")) or []
    price_id = ((items[0].get("price") or {}).get("id")) if items else None
    plan = repo.get_plan_by_provider_price(price_id) if price_id else None
    status = subscription.get("status")
    customer_id = subscription.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    start = subscription.get("current_period_start") or (items[0].get("current_period_start") if items else None)
    end = subscription.get("current_period_end") or (items[0].get("current_period_end") if items else None)

    if status in _ENDED:
        fallback_slug = get_settings().stripe_fallback_plan_slug.strip()
        fallback = repo.get_plan_by_slug(fallback_slug) if fallback_slug else None
        current = repo.get_subscription_for_tenant(tenant_id)
        if current is None or (current.get("provider_subscription_id") not in (None, subscription_id)):
            return "ended_not_current"  # an old subscription ending must not touch the tenant's newer one
        now = datetime.now(timezone.utc).isoformat()
        if fallback is not None:
            repo.sync_provider_subscription(tenant_id, fallback["id"], "active", now, _iso(end) or now, "stripe",
                                            customer_id, None, canceled_at=_iso(subscription.get("canceled_at")) or now)
            return "ended_fallback_plan"
        repo.sync_provider_subscription(tenant_id, current["plan_id"], "canceled", str(current["current_period_start"]),
                                        str(current["current_period_end"]), "stripe", customer_id, subscription_id,
                                        canceled_at=_iso(subscription.get("canceled_at")) or now)
        return "ended"

    if status not in _GRANTING:
        return f"not_granted_{status}"  # e.g. "incomplete": the first payment hasn't gone through
    if plan is None:
        logger.error("Stripe subscription %s uses price %s, which no plan is set to - ignored.", subscription_id, price_id)
        return "unknown_price"

    repo.sync_provider_subscription(
        tenant_id, plan["id"], _GRANTING[status], _iso(start) or datetime.now(timezone.utc).isoformat(),
        _iso(end) or datetime.now(timezone.utc).isoformat(), "stripe", customer_id, subscription_id,
        canceled_at=None,
    )
    return f"synced_{_GRANTING[status]}"

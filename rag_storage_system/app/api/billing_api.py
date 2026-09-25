"""
Billing / Subscription API (Phase 5 Step 25) - Owner-JWT scoped, same
as app/api/complaint_api.py. Every endpoint here only ever reads or
writes the CALLER's own tenant's billing data (owner["tenant_id"]) -
there is no endpoint that takes a tenant_id as input, so one tenant's
Owner can never view or change another tenant's plan/subscription/usage.

Endpoints:
    GET  /admin/billing/plans                    the plan catalog (any Owner/attorney/paralegal)
    POST /admin/billing/plans                     create a plan (Owner only - see app/security/auth.py's require_owner_role)
    GET  /admin/billing/subscription               the caller's tenant's current subscription + plan
    POST /admin/billing/subscription               assign the caller's tenant to a plan (Owner only)
    PUT  /admin/billing/subscription                move the caller's tenant's subscription to a different plan (Owner only)
    POST /admin/billing/subscription/cancel         cancel the caller's tenant's subscription (Owner only)
    GET  /admin/billing/usage                       the caller's tenant's current usage vs. its plan's limits
    GET  /admin/billing/provider                    which provider is on, and what the caller can do
    POST /admin/billing/checkout                    Stripe: a Checkout page URL for a paid plan (Owner only)
    POST /admin/billing/portal                      Stripe: a Billing Portal URL (card, invoices, cancel) (Owner only)
    PUT  /admin/billing/plans/{id}/provider-price   set a plan's Stripe price (plan admins only)
    POST /billing/stripe/webhook                    Stripe -> us, signature-verified (no login)

With BILLING_PROVIDER=stripe, a paid plan is granted only by Stripe's
signed webhook after payment (app/billing/stripe_webhooks.py) - assigning
it directly is refused (409), so an owner can't give themselves a paid
plan without paying.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas import (
    BillingProviderInfo,
    BillingUsageResponse,
    CheckoutRequest,
    PlanPriceRequest,
    RedirectResponse,
    ChangePlanRequest,
    PlanCreateRequest,
    PlanInfo,
    PlanLimitsInfo,
    PlanListResponse,
    SubscribeRequest,
    SubscriptionInfo,
    UsageInfo,
)
from app.billing import get_billing_provider, get_billing_service
from app.billing.stripe_provider import CheckoutRequired, StripeError, WebhookSignatureError, verify_webhook
from app.security.auth import require_admin_key, require_owner_role
from config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/billing", tags=["billing"], dependencies=[Depends(require_admin_key)])
webhook_router = APIRouter(tags=["billing-webhooks"])


def _stripe_on() -> bool:
    return get_settings().billing_provider == "stripe"


def _can_manage_plans(owner: dict) -> bool:
    """Plans are one catalog for every organization, so creating/pricing them is a platform-admin job."""

    admins = {e.strip().lower() for e in get_settings().billing_plan_admin_emails.split(",") if e.strip()}
    if owner.get("role") != "owner":
        return False
    if admins:
        return (owner.get("email") or "").lower() in admins
    return not _stripe_on()  # manual billing keeps its original behavior; Stripe requires the allow-list


def _provider_errors(action):
    try:
        return action()
    except CheckoutRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


def _plan_info(plan: dict) -> PlanInfo:
    return PlanInfo(
        id=plan["id"], slug=plan["slug"], name=plan["name"], description=plan.get("description"),
        price_cents=plan["price_cents"], billing_interval=plan["billing_interval"],
        max_matters=plan.get("max_matters"), max_documents=plan.get("max_documents"),
        max_storage_bytes=plan.get("max_storage_bytes"), max_llm_calls_per_month=plan.get("max_llm_calls_per_month"),
        max_owners=plan.get("max_owners"), is_active=bool(plan["is_active"]), created_at=str(plan["created_at"]),
        provider_price_id=plan.get("provider_price_id"),
    )


def _subscription_info(subscription: dict) -> SubscriptionInfo:
    return SubscriptionInfo(
        tenant_id=subscription["tenant_id"], status=subscription["status"],
        current_period_start=str(subscription["current_period_start"]),
        current_period_end=str(subscription["current_period_end"]),
        trial_end=str(subscription["trial_end"]) if subscription.get("trial_end") else None,
        canceled_at=str(subscription["canceled_at"]) if subscription.get("canceled_at") else None,
        plan=_plan_info(subscription["plan"]),
    )


@router.get("/plans", response_model=PlanListResponse)
def list_plans() -> PlanListResponse:
    """The global plan catalog - every active plan a tenant could subscribe to."""

    from app.api import storage_api

    plans = get_billing_service(storage_api.metadata_repository).list_plans(active_only=True)
    return PlanListResponse(plans=[_plan_info(p) for p in plans])


@router.post("/plans", response_model=PlanInfo)
def create_plan(request: PlanCreateRequest, owner: dict = Depends(require_owner_role)) -> PlanInfo:
    """
    Create a new plan with configurable limits/entitlements - Owner
    only. A limit left unset in the request is stored as NULL, which
    app/billing/service.py's check_limit() always treats as unlimited.
    """

    from app.api import storage_api

    if not _can_manage_plans(owner):
        raise HTTPException(status_code=403, detail="Only the platform's plan admins (BILLING_PLAN_ADMIN_EMAILS) may create plans.")

    values = request.model_dump()
    price_id = values.pop("provider_price_id", None)
    try:
        plan = get_billing_service(storage_api.metadata_repository).create_plan(**values)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not create plan: {exc}")
    if price_id:
        plan = storage_api.metadata_repository.set_plan_provider_price(plan["id"], price_id.strip())

    return _plan_info(plan)


@router.put("/plans/{plan_id}/provider-price", response_model=PlanInfo)
def set_plan_price(plan_id: int, request: PlanPriceRequest, owner: dict = Depends(require_owner_role)) -> PlanInfo:
    """Set (or clear) the Stripe Price a plan is sold at - plan admins only."""

    from app.api import storage_api

    if not _can_manage_plans(owner):
        raise HTTPException(status_code=403, detail="Only the platform's plan admins (BILLING_PLAN_ADMIN_EMAILS) may price plans.")
    repo = storage_api.metadata_repository
    if repo.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    price_id = (request.provider_price_id or "").strip() or None
    if price_id and not price_id.startswith("price_"):
        raise HTTPException(status_code=400, detail="A Stripe price id starts with 'price_'.")
    return _plan_info(repo.set_plan_provider_price(plan_id, price_id))


@router.get("/subscription", response_model=SubscriptionInfo)
def get_subscription(owner: dict = Depends(require_admin_key)) -> SubscriptionInfo:
    """The caller's own tenant's current subscription, plan, status, and billing period - never another tenant's."""

    from app.api import storage_api

    subscription = get_billing_service(storage_api.metadata_repository).get_subscription(owner["tenant_id"])
    if subscription is None:
        raise HTTPException(status_code=404, detail="This tenant has no subscription yet.")

    return _subscription_info(subscription)


@router.post("/subscription", response_model=SubscriptionInfo)
def subscribe(request: SubscribeRequest, owner: dict = Depends(require_owner_role)) -> SubscriptionInfo:
    """Assign the caller's own tenant to a plan - Owner only. Creates the subscription if none exists yet, or reassigns it otherwise."""

    from app.api import storage_api

    try:
        _provider_errors(lambda: get_billing_service(storage_api.metadata_repository).subscribe(
            owner["tenant_id"], request.plan_slug, trial_days=request.trial_days
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _subscription_info(get_billing_service(storage_api.metadata_repository).get_subscription(owner["tenant_id"]))


@router.put("/subscription", response_model=SubscriptionInfo)
def change_plan(request: ChangePlanRequest, owner: dict = Depends(require_owner_role)) -> SubscriptionInfo:
    """Move the caller's own tenant's EXISTING subscription to a different plan - Owner only."""

    from app.api import storage_api

    try:
        _provider_errors(lambda: get_billing_service(storage_api.metadata_repository).change_plan(
            owner["tenant_id"], request.plan_slug
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _subscription_info(get_billing_service(storage_api.metadata_repository).get_subscription(owner["tenant_id"]))


@router.post("/subscription/cancel", response_model=SubscriptionInfo)
def cancel_subscription(owner: dict = Depends(require_owner_role)) -> SubscriptionInfo:
    """Cancel the caller's own tenant's subscription - Owner only."""

    from app.api import storage_api

    service = get_billing_service(storage_api.metadata_repository)
    subscription = _provider_errors(lambda: service.cancel(owner["tenant_id"]))
    if subscription is None:
        raise HTTPException(status_code=404, detail="This tenant has no subscription to cancel.")

    return _subscription_info(service.get_subscription(owner["tenant_id"]))


@router.get("/usage", response_model=BillingUsageResponse)
def get_usage(owner: dict = Depends(require_admin_key)) -> BillingUsageResponse:
    """The caller's own tenant's current usage (matters/documents/storage/LLM calls this period) alongside its plan's limits."""

    from app.api import storage_api

    service = get_billing_service(storage_api.metadata_repository)
    usage = service.get_usage(owner["tenant_id"])
    subscription = service.get_subscription(owner["tenant_id"])

    limits = None
    if subscription is not None:
        plan = subscription["plan"]
        limits = PlanLimitsInfo(
            max_matters=plan.get("max_matters"), max_documents=plan.get("max_documents"),
            max_storage_bytes=plan.get("max_storage_bytes"),
            max_llm_calls_per_month=plan.get("max_llm_calls_per_month"),
        )

    return BillingUsageResponse(usage=UsageInfo(**usage), limits=limits)


# ----------------------------------------------------------------------
# Stripe: Checkout, Billing Portal, webhook
# ----------------------------------------------------------------------

def _frontend(path: str) -> str:
    return get_settings().frontend_base_url.rstrip("/") + path


@router.get("/provider", response_model=BillingProviderInfo)
def billing_provider_info(owner: dict = Depends(require_admin_key)) -> BillingProviderInfo:
    from app.api import storage_api

    subscription = storage_api.metadata_repository.get_subscription_for_tenant(owner["tenant_id"])
    return BillingProviderInfo(
        provider=get_settings().billing_provider,
        checkout_enabled=_stripe_on(),
        can_manage_billing=_stripe_on() and bool(subscription and subscription.get("provider_customer_id")),
        can_manage_plans=_can_manage_plans(owner),
    )


@router.post("/checkout", response_model=RedirectResponse)
def start_checkout(request: CheckoutRequest, owner: dict = Depends(require_owner_role)) -> RedirectResponse:
    """A Stripe Checkout page for a paid plan. Nothing changes here until Stripe confirms payment by webhook."""

    from app.api import storage_api

    if not _stripe_on():
        raise HTTPException(status_code=409, detail="Online payment is not enabled (BILLING_PROVIDER is not 'stripe').")
    repo = storage_api.metadata_repository
    plan = repo.get_plan_by_slug(request.plan_slug)
    if plan is None or not plan["is_active"]:
        raise HTTPException(status_code=404, detail="Plan not found.")
    if int(plan["price_cents"] or 0) <= 0:
        raise HTTPException(status_code=400, detail="This plan is free - choose it without checkout.")
    subscription = repo.get_subscription_for_tenant(owner["tenant_id"])
    if subscription and subscription.get("provider_subscription_id") and subscription["status"] != "canceled":
        raise HTTPException(status_code=409, detail="You already pay through Stripe - change plans from Manage billing.")

    url = _provider_errors(lambda: get_billing_provider().create_checkout_session(
        owner["tenant_id"], plan, subscription.get("provider_customer_id") if subscription else None,
        owner.get("email"), _frontend("/billing?checkout=success"), _frontend("/billing?checkout=canceled"),
    ))
    return RedirectResponse(url=url)


@router.post("/portal", response_model=RedirectResponse)
def open_billing_portal(owner: dict = Depends(require_owner_role)) -> RedirectResponse:
    """Stripe's Billing Portal: update the card, see invoices, cancel. Card details never touch this server."""

    from app.api import storage_api

    if not _stripe_on():
        raise HTTPException(status_code=409, detail="Online payment is not enabled.")
    subscription = storage_api.metadata_repository.get_subscription_for_tenant(owner["tenant_id"])
    if not subscription or not subscription.get("provider_customer_id"):
        raise HTTPException(status_code=404, detail="No Stripe billing account yet - subscribe to a paid plan first.")
    url = _provider_errors(lambda: get_billing_provider().create_portal_session(
        subscription["provider_customer_id"], _frontend("/billing")
    ))
    return RedirectResponse(url=url)


@webhook_router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Stripe -> us. Refused unless signed with STRIPE_WEBHOOK_SECRET; a Stripe outage is reported as 503 so Stripe retries."""

    from app.api import storage_api
    from app.billing.stripe_webhooks import handle_event

    if not _stripe_on():
        raise HTTPException(status_code=404, detail="Not found.")
    payload = await request.body()
    try:
        event = verify_webhook(payload, request.headers.get("stripe-signature"), get_settings().stripe_webhook_secret)
    except WebhookSignatureError as exc:
        logger.warning("Stripe webhook refused: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature.")

    repo = storage_api.metadata_repository
    try:
        outcome = handle_event(event, repo, get_billing_provider())
    except StripeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    repo.record_provider_event(event.get("id", ""), "stripe", event.get("type", ""), None)
    logger.info("Stripe event %s (%s): %s", event.get("id"), event.get("type"), outcome)
    return {"received": True, "outcome": outcome}

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
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import (
    BillingUsageResponse,
    ChangePlanRequest,
    PlanCreateRequest,
    PlanInfo,
    PlanLimitsInfo,
    PlanListResponse,
    SubscribeRequest,
    SubscriptionInfo,
    UsageInfo,
)
from app.billing import get_billing_service
from app.security.auth import require_admin_key, require_owner_role

router = APIRouter(prefix="/admin/billing", tags=["billing"], dependencies=[Depends(require_admin_key)])


def _plan_info(plan: dict) -> PlanInfo:
    return PlanInfo(
        id=plan["id"], slug=plan["slug"], name=plan["name"], description=plan.get("description"),
        price_cents=plan["price_cents"], billing_interval=plan["billing_interval"],
        max_matters=plan.get("max_matters"), max_documents=plan.get("max_documents"),
        max_storage_bytes=plan.get("max_storage_bytes"), max_llm_calls_per_month=plan.get("max_llm_calls_per_month"),
        max_owners=plan.get("max_owners"), is_active=bool(plan["is_active"]), created_at=str(plan["created_at"]),
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

    try:
        plan = get_billing_service(storage_api.metadata_repository).create_plan(**request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not create plan: {exc}")

    return _plan_info(plan)


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
        get_billing_service(storage_api.metadata_repository).subscribe(
            owner["tenant_id"], request.plan_slug, trial_days=request.trial_days
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _subscription_info(get_billing_service(storage_api.metadata_repository).get_subscription(owner["tenant_id"]))


@router.put("/subscription", response_model=SubscriptionInfo)
def change_plan(request: ChangePlanRequest, owner: dict = Depends(require_owner_role)) -> SubscriptionInfo:
    """Move the caller's own tenant's EXISTING subscription to a different plan - Owner only."""

    from app.api import storage_api

    try:
        get_billing_service(storage_api.metadata_repository).change_plan(owner["tenant_id"], request.plan_slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _subscription_info(get_billing_service(storage_api.metadata_repository).get_subscription(owner["tenant_id"]))


@router.post("/subscription/cancel", response_model=SubscriptionInfo)
def cancel_subscription(owner: dict = Depends(require_owner_role)) -> SubscriptionInfo:
    """Cancel the caller's own tenant's subscription - Owner only."""

    from app.api import storage_api

    service = get_billing_service(storage_api.metadata_repository)
    subscription = service.cancel(owner["tenant_id"])
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

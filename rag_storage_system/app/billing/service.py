"""
Core billing/subscription business logic (Phase 5 Step 25). Every
method takes a MetadataRepository (the same tenant-scoped repository
app/api/storage_api.py already uses for matters/documents/prompts/the
cause-of-action library/llm_usage_log - app/metadata/base.py) so this
works against both the SQLite test backend and the real Postgres
backend with zero code differences, same as everything else in this
codebase. It is never a second, parallel tenant or usage-tracking
system.

PAYMENT-PROVIDER SEPARATION: this module never talks to a payment
gateway directly - only to whatever app/billing/__init__.py's
get_billing_provider() returns (see app/billing/provider.py). A
ManualPaymentProvider today, a real Stripe integration later - this
file does not change either way.

ENFORCEMENT: check_limit() is the one chokepoint every quota-checked
API endpoint calls before doing the thing that consumes a resource
(app/api/storage_api.py's create_matter/upload_document/research
endpoints, app/api/end_user_api.py's query/compare endpoints) - see
its own docstring for exactly when it blocks vs. fails open.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.metadata.base import MetadataRepository

RESOURCE_MATTERS = "matters"
RESOURCE_DOCUMENTS = "documents"
RESOURCE_STORAGE_BYTES = "storage_bytes"
RESOURCE_LLM_CALLS = "llm_calls_per_month"

_LIMIT_COLUMN_BY_RESOURCE = {
    RESOURCE_MATTERS: "max_matters",
    RESOURCE_DOCUMENTS: "max_documents",
    RESOURCE_STORAGE_BYTES: "max_storage_bytes",
    RESOURCE_LLM_CALLS: "max_llm_calls_per_month",
}


class PlanLimitExceededError(Exception):
    """Raised by check_limit() - app/api endpoints catch this and return HTTP 402 Payment Required."""

    def __init__(self, resource: str, limit: int, attempted: int):
        self.resource = resource
        self.limit = limit
        self.attempted = attempted
        super().__init__(
            f"Plan limit exceeded for '{resource}': {attempted} would exceed the plan's limit of {limit}."
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _period_end(start_iso: str, days: int = 30) -> str:
    return (datetime.fromisoformat(start_iso) + timedelta(days=days)).isoformat()


def _period_start_of_month() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


class BillingService:

    def __init__(self, metadata_repository: MetadataRepository, provider=None):
        self._repo = metadata_repository
        self._provider = provider

    # ------------------------------------------------------------------
    # Plans - a global catalog, not tenant-owned.
    # ------------------------------------------------------------------

    def list_plans(self, active_only: bool = False) -> list[dict]:
        return self._repo.list_plans(active_only=active_only)

    def get_plan(self, plan_id: int) -> Optional[dict]:
        return self._repo.get_plan(plan_id)

    def create_plan(
        self, slug: str, name: str, description: Optional[str] = None, price_cents: int = 0,
        billing_interval: str = "monthly", max_matters: Optional[int] = None,
        max_documents: Optional[int] = None, max_storage_bytes: Optional[int] = None,
        max_llm_calls_per_month: Optional[int] = None, max_owners: Optional[int] = None,
    ) -> dict:
        return self._repo.create_plan(
            slug=slug, name=name, description=description, price_cents=price_cents,
            billing_interval=billing_interval, max_matters=max_matters, max_documents=max_documents,
            max_storage_bytes=max_storage_bytes, max_llm_calls_per_month=max_llm_calls_per_month,
            max_owners=max_owners,
        )

    # ------------------------------------------------------------------
    # Subscriptions - exactly one row per tenant.
    # ------------------------------------------------------------------

    def get_subscription(self, tenant_id: int) -> Optional[dict]:
        """The tenant's subscription row, with its plan embedded under "plan" - or None if it was never assigned one."""

        subscription = self._repo.get_subscription_for_tenant(tenant_id)
        if subscription is None:
            return None

        return {**subscription, "plan": self._repo.get_plan(subscription["plan_id"])}

    def subscribe(self, tenant_id: int, plan_slug: str, trial_days: Optional[int] = None) -> dict:
        """
        Assign `tenant_id` to the plan named `plan_slug` - creates its
        subscription if it has none yet, or moves it onto this plan
        otherwise (see change_plan() for moving an EXISTING
        subscription to a different plan as its own explicit action).

        Real functionality: this writes a real tenant_subscriptions
        row. It never fabricates a payment or invoice - the configured
        PaymentProvider (app/billing/provider.py) is only ever asked
        to do whatever provider-side setup it actually performs
        (nothing, for the default ManualPaymentProvider).
        """

        plan = self._repo.get_plan_by_slug(plan_slug)
        if plan is None:
            raise ValueError(f"No such plan: {plan_slug!r}")

        now = _now_iso()

        if self._provider is not None:
            provider_result = self._provider.start_subscription(tenant_id, plan)
        else:
            provider_result = None

        existing = self._repo.get_subscription_for_tenant(tenant_id)
        if existing is not None:
            return self._repo.change_tenant_plan(
                tenant_id, plan["id"], current_period_start=now, current_period_end=_period_end(now)
            )

        status = "trialing" if trial_days else "active"
        trial_end = _period_end(now, trial_days) if trial_days else None

        return self._repo.create_tenant_subscription(
            tenant_id, plan["id"], status=status, current_period_start=now,
            current_period_end=_period_end(now), trial_end=trial_end,
            provider=provider_result.provider if provider_result else None,
            provider_customer_id=provider_result.provider_customer_id if provider_result else None,
            provider_subscription_id=provider_result.provider_subscription_id if provider_result else None,
        )

    def change_plan(self, tenant_id: int, plan_slug: str) -> dict:
        """Move an EXISTING subscription to a different plan - raises if `tenant_id` has none yet (use subscribe() first)."""

        plan = self._repo.get_plan_by_slug(plan_slug)
        if plan is None:
            raise ValueError(f"No such plan: {plan_slug!r}")

        subscription = self._repo.get_subscription_for_tenant(tenant_id)
        if subscription is None:
            raise ValueError(f"Tenant {tenant_id} has no subscription yet - call subscribe() first.")

        if self._provider is not None:
            self._provider.change_subscription(tenant_id, subscription.get("provider_subscription_id"), plan)

        now = _now_iso()
        return self._repo.change_tenant_plan(
            tenant_id, plan["id"], current_period_start=now, current_period_end=_period_end(now)
        )

    def cancel(self, tenant_id: int) -> Optional[dict]:
        subscription = self._repo.get_subscription_for_tenant(tenant_id)
        if subscription is None:
            return None

        if self._provider is not None:
            self._provider.cancel_subscription(tenant_id, subscription.get("provider_subscription_id"))

        return self._repo.update_subscription_status(tenant_id, "canceled", canceled_at=_now_iso())

    # ------------------------------------------------------------------
    # Usage / enforcement
    # ------------------------------------------------------------------

    def get_usage(self, tenant_id: int) -> dict:
        """
        Current usage for every metered resource - matters/documents
        counted directly from their own tables, storage summed from
        documents.size, and LLM calls counted from the existing
        llm_usage_log table for the tenant's current billing period
        (or the calendar month, if it has no subscription yet). Never
        a second, parallel usage-tracking system.
        """

        resource_usage = self._repo.get_tenant_resource_usage(tenant_id)
        subscription = self._repo.get_subscription_for_tenant(tenant_id)
        period_start = subscription["current_period_start"] if subscription else _period_start_of_month()
        llm_calls = self._repo.count_llm_usage_since(tenant_id, period_start)

        return {
            RESOURCE_MATTERS: resource_usage["matters"],
            RESOURCE_DOCUMENTS: resource_usage["documents"],
            RESOURCE_STORAGE_BYTES: resource_usage["storage_bytes"],
            RESOURCE_LLM_CALLS: llm_calls,
        }

    def check_limit(self, tenant_id: int, resource: str, requested_increment: int = 1) -> None:
        """
        Raise PlanLimitExceededError if consuming `requested_increment`
        more of `resource` would exceed the tenant's plan's limit for
        it. Fails OPEN (never raises) when:

          - the tenant has no subscription row at all - keeps every
            tenant/test that predates billing (or was simply never
            put on a plan) working exactly as it did before this
            feature existed, same fail-open philosophy the tenant_id
            multi-tenancy retrofit itself used for untenanted callers; or
          - the assigned plan has no limit set for `resource` (a NULL
            column - see database/migrations/0017_billing.sql -
            explicitly means "unlimited", not "unset/unknown").

        A subscription whose status is "past_due" or "canceled" still
        has its plan's limits enforced here exactly like "active" -
        MVP scope is "enforce the assigned plan's limits", not a
        separate "block this tenant entirely" gate.
        """

        subscription = self._repo.get_subscription_for_tenant(tenant_id)
        if subscription is None:
            return

        plan = self._repo.get_plan(subscription["plan_id"])
        if plan is None:
            return

        limit = plan.get(_LIMIT_COLUMN_BY_RESOURCE[resource])
        if limit is None:
            return

        if resource == RESOURCE_LLM_CALLS:
            current = self._repo.count_llm_usage_since(tenant_id, subscription["current_period_start"])
        else:
            current = self._repo.get_tenant_resource_usage(tenant_id)[resource]

        attempted = current + requested_increment
        if attempted > limit:
            raise PlanLimitExceededError(resource, limit, attempted)

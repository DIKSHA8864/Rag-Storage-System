"""
Payment provider interface. Same abstraction principle as
app/analysis/base.py's NarrativeGenerator and app/embeddings/base.py:
app/billing/service.py (the core billing logic - plans, subscriptions,
usage/limit enforcement) never talks to a payment gateway's SDK
directly, only to whatever implements PaymentProvider. Swapping in a
real gateway (Stripe or otherwise) later is a new class here plus a
factory branch in app/billing/__init__.py's get_billing_provider() -
never a change to BillingService or any API endpoint.

ManualPaymentProvider is the only implementation today. It does not
call any external payment gateway and never fabricates a charge,
invoice, or transaction record - "manual" billing (an Owner/Admin
assigns a tenant to a plan directly, the same way a sales-assisted or
invoiced B2B deal works before self-serve checkout exists) is real,
common SaaS behavior, not a mock of a real integration. It exists so
BillingService has a concrete provider to depend on now, without the
system ever pretending a card was charged.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderSubscriptionResult:
    """
    What a PaymentProvider hands back after starting/changing a
    subscription - BillingService stores these verbatim on the
    tenant_subscriptions row (provider/provider_customer_id/
    provider_subscription_id). All fields are None for
    ManualPaymentProvider, since there is no external provider.
    """

    provider: Optional[str] = None
    provider_customer_id: Optional[str] = None
    provider_subscription_id: Optional[str] = None


class PaymentProvider(ABC):
    """
    Abstract base class for all payment-provider integrations. A real
    implementation (e.g. StripePaymentProvider) would call out to that
    gateway's API in every method below; BillingService only ever
    calls these methods, never a gateway SDK.
    """

    @abstractmethod
    def start_subscription(self, tenant_id: int, plan: dict) -> ProviderSubscriptionResult:
        """Begin billing `tenant_id` for `plan` with this provider. Returns provider-side identifiers to persist, if any."""
        raise NotImplementedError

    @abstractmethod
    def change_subscription(self, tenant_id: int, provider_subscription_id: Optional[str], new_plan: dict) -> ProviderSubscriptionResult:
        """Move an existing provider-side subscription to `new_plan`."""
        raise NotImplementedError

    @abstractmethod
    def cancel_subscription(self, tenant_id: int, provider_subscription_id: Optional[str]) -> None:
        """Cancel the provider-side subscription, if one exists."""
        raise NotImplementedError


class ManualPaymentProvider(PaymentProvider):
    """
    The default, real (not fake) provider: billing is administered
    directly by an Owner/Admin through app/api/billing_api.py, with no
    external payment gateway involved. Every method is a no-op that
    returns "no external provider" - BillingService still creates a
    real tenant_subscriptions row either way, it just never carries a
    provider/provider_*_id.
    """

    def start_subscription(self, tenant_id: int, plan: dict) -> ProviderSubscriptionResult:
        return ProviderSubscriptionResult()

    def change_subscription(self, tenant_id: int, provider_subscription_id: Optional[str], new_plan: dict) -> ProviderSubscriptionResult:
        return ProviderSubscriptionResult()

    def cancel_subscription(self, tenant_id: int, provider_subscription_id: Optional[str]) -> None:
        return None

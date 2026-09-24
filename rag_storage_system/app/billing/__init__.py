"""
Payment provider factory - the single place that decides which
PaymentProvider implementation app/billing/service.py's BillingService
talks to, mirroring app/analysis/__init__.py's get_narrative_generator()
and app/embeddings/__init__.py's get_embedding_provider().

Controlled by BILLING_PROVIDER (config/settings.py / .env):
    "manual" (default) -> ManualPaymentProvider - no external payment
        gateway; an Owner/Admin assigns tenants to plans directly via
        app/api/billing_api.py. Real functionality, not a mock.

A real gateway (e.g. "stripe") is a future addition: add the
implementation class in app/billing/provider.py and a branch below -
BillingService and every API endpoint stay unchanged either way.
"""

from app.billing.provider import PaymentProvider

_provider_instance: PaymentProvider | None = None


def get_billing_provider() -> PaymentProvider:
    global _provider_instance

    if _provider_instance is None:
        from config.settings import get_settings

        settings = get_settings()

        if settings.billing_provider == "manual":
            from app.billing.provider import ManualPaymentProvider

            _provider_instance = ManualPaymentProvider()
        else:
            raise NotImplementedError(
                f"BILLING_PROVIDER={settings.billing_provider!r} has no implementation yet - "
                "add one to app/billing/provider.py and a branch here. Falling back to a fake "
                "provider is deliberately not done, per the no-fake-payments rule."
            )

    return _provider_instance


def get_billing_service(metadata_repository):
    """
    Build a BillingService bound to `metadata_repository` and the
    configured PaymentProvider. Deliberately NOT cached/module-level
    like get_billing_provider() above - callers (app/api/billing_api.py,
    app/api/storage_api.py, app/api/end_user_api.py) always pass in
    whatever their own module's current `metadata_repository` is at
    call time, so tests that monkeypatch it per-test (see
    tests/conftest.py) are respected instead of a stale repository
    instance getting captured once at import time.
    """

    from app.billing.service import BillingService

    return BillingService(metadata_repository, get_billing_provider())

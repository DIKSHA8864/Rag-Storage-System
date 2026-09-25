-- Stripe billing (Blueprint Phase 5). BILLING_PROVIDER=stripe only; the
-- default manual provider ignores all of this. Idempotent.

-- The Stripe Price (price_...) a paid plan is sold at.
ALTER TABLE plans ADD COLUMN IF NOT EXISTS provider_price_id VARCHAR(255);

-- Every webhook event already applied, so a retried delivery is a no-op.
CREATE TABLE IF NOT EXISTS billing_provider_events (
    event_id VARCHAR(255) PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    tenant_id INTEGER,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_provider_sub ON tenant_subscriptions (provider_subscription_id);

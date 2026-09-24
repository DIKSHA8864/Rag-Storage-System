-- 0017_billing.sql
-- Phase 5 Step 25: tenant-level billing/subscription foundation.
-- `plans` are global (not tenant-owned) - a shared catalog every
-- tenant subscribes to one of, same as any SaaS pricing page.
-- `tenant_subscriptions` links exactly one active plan to a tenant at
-- a time (UNIQUE tenant_id). A NULL limit column on a plan means
-- "unlimited" - app/billing/service.py never enforces a NULL limit.

CREATE TABLE IF NOT EXISTS plans (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_cents INTEGER NOT NULL DEFAULT 0,
    billing_interval VARCHAR(20) NOT NULL DEFAULT 'monthly',
    max_matters INTEGER,
    max_documents INTEGER,
    max_storage_bytes BIGINT,
    max_llm_calls_per_month INTEGER,
    max_owners INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER UNIQUE NOT NULL REFERENCES tenants(id),
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    trial_end TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    -- provider/provider_*_id are deliberately nullable and unused
    -- today (see app/billing/provider.py's ManualPaymentProvider) -
    -- the columns exist now so a future real PaymentProvider (Stripe
    -- or otherwise) can populate them without another migration.
    provider VARCHAR(50),
    provider_customer_id VARCHAR(255),
    provider_subscription_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the same real, explicitly unlimited plan the SQLite backend
-- seeds (app/metadata/sqlite_repository.py) for the pre-existing
-- Default Organization tenant, so Phase 1-4 behavior is unchanged
-- until an Owner is deliberately moved onto a real, limited plan.
INSERT INTO plans (id, slug, name, description, price_cents, billing_interval, is_active)
VALUES (1, 'default-unlimited', 'Default (Unlimited)',
        'Seeded for the pre-existing Default Organization tenant - every limit is unlimited.',
        0, 'monthly', TRUE)
ON CONFLICT (id) DO NOTHING;

SELECT setval('plans_id_seq', GREATEST((SELECT MAX(id) FROM plans), 1));

INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status, current_period_start, current_period_end)
VALUES (1, 1, 1, 'active', NOW(), NOW() + INTERVAL '30 days')
ON CONFLICT (tenant_id) DO NOTHING;

SELECT setval('tenant_subscriptions_id_seq', GREATEST((SELECT MAX(id) FROM tenant_subscriptions), 1));

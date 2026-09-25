-- Per-organization (tenant) disclaimer and retrieval settings, so one
-- firm's admin can never change another firm's answers or disclaimers.
-- The old single-row `disclaimer` / `retrieval_settings` tables are kept
-- as the Default Organization's (tenant 1) fallback until it saves its
-- own - so settings saved before this migration keep applying.
-- Idempotent (re-applied on every startup).

CREATE TABLE IF NOT EXISTS tenant_disclaimers (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    text TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS tenant_retrieval_settings (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    top_k INTEGER NOT NULL,
    score_threshold DOUBLE PRECISION NOT NULL,
    min_chunks INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255)
);

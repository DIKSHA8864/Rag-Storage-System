-- 0018_end_user_accounts.sql
-- Individual end-user accounts (replacing shared per-Matter access
-- codes as the normal way end users sign in - see
-- app/security/end_user_accounts.py). The Owner/Admin invites each
-- email; only an invited email can complete signup, which requires a
-- one-time code sent to that inbox. Each account gets its own
-- personal Matter on activation, so every existing Matter-scoped
-- isolation rule (intake sessions, threads, Q&A) applies unchanged.

CREATE TABLE IF NOT EXISTS end_users (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
    -- Globally unique: login is by email alone, with no tenant selector.
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'invited',
    matter_id INTEGER,
    -- Bumped on every password reset and deactivation; every issued
    -- session token carries the value it was issued with, so bumping
    -- it invalidates all of that account's existing sessions at once.
    session_version INTEGER NOT NULL DEFAULT 0,
    invited_by VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_end_users_tenant ON end_users (tenant_id);

CREATE TABLE IF NOT EXISTS verification_codes (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    purpose VARCHAR(30) NOT NULL,
    -- HMAC of the code, keyed by JWT_SECRET_KEY - never the code itself.
    code_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_verification_codes_lookup ON verification_codes (email, purpose, created_at);

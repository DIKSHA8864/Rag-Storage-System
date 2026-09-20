-- 0007_matters.sql
-- Multiple isolated End User identities ("matters") - each gets its
-- own X-End-User-Key. Threads (0008) are scoped to matter_id, giving
-- real isolation instead of one shared key for everyone.

CREATE TABLE IF NOT EXISTS matters (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    api_key_hash VARCHAR(64) UNIQUE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
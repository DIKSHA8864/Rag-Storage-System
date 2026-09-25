-- "Talk to a person" (Blueprint Phase 5): a client asks for a human during
-- intake; the firm's staff see, claim and close the request. Idempotent.
SELECT rag_retire_legacy_table('handoff_requests', 'contact_method');

CREATE TABLE IF NOT EXISTS handoff_requests (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    matter_id INTEGER NOT NULL,
    intake_session_id INTEGER,
    end_user_id INTEGER,
    contact_method VARCHAR(20) NOT NULL,      -- phone | email | video
    contact_value VARCHAR(255) NOT NULL,
    preferred_time VARCHAR(255),
    message TEXT,
    language VARCHAR(5),
    status VARCHAR(20) NOT NULL DEFAULT 'open',   -- open | claimed | closed
    claimed_by VARCHAR(255),
    closed_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_handoff_requests_tenant_status ON handoff_requests (tenant_id, status);

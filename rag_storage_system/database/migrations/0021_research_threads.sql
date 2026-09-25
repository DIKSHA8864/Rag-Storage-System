-- Owner research threads (Blueprint Work Plan M3: "Threads persisted; any
-- thread or answer exports ... as a .docx/.pdf memo"). A thread belongs to
-- the admin user who started it (owner_sub = their login's subject) within
-- their organization. Idempotent (re-applied on every startup).

SELECT rag_retire_legacy_table('research_messages', 'sources');
SELECT rag_retire_legacy_table('research_threads', 'owner_sub');

CREATE TABLE IF NOT EXISTS research_threads (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    owner_sub VARCHAR(64) NOT NULL,
    title VARCHAR(200) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_threads_owner
    ON research_threads (tenant_id, owner_sub, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_messages (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES research_threads(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_messages_thread ON research_messages (thread_id, id);

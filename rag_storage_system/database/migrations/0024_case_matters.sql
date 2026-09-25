-- One matter per case (Blueprint Phase 4): every new intake a signed-in
-- client starts opens its own case matter, and attorneys upload that
-- case's documents (pleadings, orders, correspondence) into it. The
-- documents are indexed only into that matter's namespace
-- ("matter-<id>"), never the library. Idempotent.

-- 'client' = a client's personal matter (their Ask threads, and intakes
-- started before case matters existed); 'case' = one case.
ALTER TABLE matters ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'client';
-- For a case matter: the client account that opened it.
ALTER TABLE matters ADD COLUMN IF NOT EXISTS end_user_id INTEGER REFERENCES end_users(id);
CREATE INDEX IF NOT EXISTS idx_matters_end_user ON matters (end_user_id);

SELECT rag_retire_legacy_table('matter_documents', 'chunk_count');

CREATE TABLE IF NOT EXISTS matter_documents (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    matter_id INTEGER NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    doc_type VARCHAR(30) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_category VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    size BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    uploaded_by VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'queued',  -- queued | indexed | failed
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_matter_documents_matter ON matter_documents (matter_id);

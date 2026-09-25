-- Vault sync (Blueprint Phase 1: "the pipeline detects added, updated, and
-- deleted files"; Work Plan M1: "maintain a file manifest (path, content
-- hash, modified time, status) in Postgres to detect adds/updates/deletes
-- reliably"). One row per synced source file; the sync only ever manages
-- library files it created itself. Idempotent (re-applied on every startup).

CREATE TABLE IF NOT EXISTS vault_sync_manifest (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    source_path TEXT NOT NULL,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size BIGINT NOT NULL,
    mtime DOUBLE PRECISION NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, source_path)
);

CREATE TABLE IF NOT EXISTS vault_sync_runs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    source TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    skipped JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_sync_runs_tenant ON vault_sync_runs (tenant_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_documents_tenant_sha256 ON documents (tenant_id, sha256);

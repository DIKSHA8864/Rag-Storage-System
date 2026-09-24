-- 0016_multi_tenancy.sql
-- Phase 5 Step 24: real tenant/organization isolation. tenant_id is
-- NOT NULL DEFAULT 1 everywhere on purpose - every pre-existing row
-- and every caller that doesn't yet pass a tenant_id keeps working
-- exactly as before, attributed to the seeded "Default Organization"
-- (id=1). New tenants created going forward get real isolation.
--
-- Every statement here must be safe to re-run: PostgresMetadataRepository
-- re-applies every migration file on EVERY startup (no migration-tracking
-- table), so a bare ADD CONSTRAINT would fail - and stop the app starting -
-- on every run after the first. Hence the pg_constraint guards below.

CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO tenants (id, name, slug)
VALUES (1, 'Default Organization', 'default')
ON CONFLICT (id) DO NOTHING;

SELECT setval('tenants_id_seq', GREATEST((SELECT MAX(id) FROM tenants), 1));

-- owners (app/security/owner_repository.py) - only applied if the
-- table already exists in this database (owners is created by
-- app/security/owner_repository.py's create_owner_table(), not by a
-- migration file, so a fresh install may not have it yet when this
-- runs - DO block avoids an error either way).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'owners') THEN
        ALTER TABLE owners ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
        CREATE INDEX IF NOT EXISTS idx_owners_tenant ON owners (tenant_id);
    END IF;
END $$;

ALTER TABLE matters ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
CREATE INDEX IF NOT EXISTS idx_matters_tenant ON matters (tenant_id);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_relative_path_key;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'documents_tenant_relative_path_key') THEN
        ALTER TABLE documents ADD CONSTRAINT documents_tenant_relative_path_key UNIQUE (tenant_id, relative_path);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant_id);

ALTER TABLE folders ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_path_key;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'folders_tenant_path_key') THEN
        ALTER TABLE folders ADD CONSTRAINT folders_tenant_path_key UNIQUE (tenant_id, path);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_folders_tenant ON folders (tenant_id);

ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE prompt_versions DROP CONSTRAINT IF EXISTS prompt_versions_name_version_key;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prompt_versions_tenant_name_version_key') THEN
        ALTER TABLE prompt_versions ADD CONSTRAINT prompt_versions_tenant_name_version_key UNIQUE (tenant_id, name, version);
    END IF;
END $$;

ALTER TABLE cause_of_action_library ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);

ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);

-- chunk_embeddings (app/vector_store/) - same guard as owners, since
-- it's created by PgVectorRepository, a separate startup path from
-- the metadata repository that applies this same migrations folder.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'chunk_embeddings') THEN
        ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;
        CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_tenant ON chunk_embeddings (tenant_id);
    END IF;
END $$;

-- email stays globally unique on purpose - login is by email alone
-- (no tenant selector in the UI), so each email must resolve to
-- exactly one owner account across the whole install.

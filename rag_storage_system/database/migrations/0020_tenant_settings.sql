-- Per-organization (tenant) disclaimer and retrieval settings, so one
-- firm's admin can never change another firm's answers or disclaimers.
-- The old single-row `disclaimer` / `retrieval_settings` tables are kept
-- as the Default Organization's (tenant 1) fallback until it saves its
-- own - so settings saved before this migration keep applying.
-- Idempotent (re-applied on every startup).

-- A table these migrations create may already exist in an older database
-- with a different shape (an earlier experiment used the same name). Such a
-- table is kept - renamed to <name>_legacy_<timestamp>, data untouched -
-- and the new table is created in its place. A table that already has the
-- new shape (detected by one of its columns) is left alone.
CREATE OR REPLACE FUNCTION rag_retire_legacy_table(tbl text, required_column text) RETURNS void AS $fn$
DECLARE
    suffix text := '_legacy_' || to_char(clock_timestamp(), 'YYYYMMDDHH24MISS');
    item record;
BEGIN
    IF to_regclass(quote_ident(tbl)) IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = tbl AND column_name = required_column
    ) THEN
        RETURN;
    END IF;
    -- Index and sequence names are schema-wide: move them out of the new table's way too.
    FOR item IN SELECT indexname AS name FROM pg_indexes WHERE schemaname = current_schema() AND tablename = tbl LOOP
        EXECUTE format('ALTER INDEX %I RENAME TO %I', item.name, left(item.name, 40) || suffix);
    END LOOP;
    FOR item IN
        SELECT s.relname AS name FROM pg_class s JOIN pg_depend d ON d.objid = s.oid
        WHERE s.relkind = 'S' AND d.refobjid = quote_ident(tbl)::regclass AND d.deptype = 'a'
    LOOP
        EXECUTE format('ALTER SEQUENCE %I RENAME TO %I', item.name, left(item.name, 40) || suffix);
    END LOOP;
    EXECUTE format('ALTER TABLE %I RENAME TO %I', tbl, left(tbl, 40) || suffix);
    RAISE NOTICE 'An older "%" table was kept as "%"', tbl, left(tbl, 40) || suffix;
END
$fn$ LANGUAGE plpgsql;

SELECT rag_retire_legacy_table('tenant_disclaimers', 'tenant_id');
SELECT rag_retire_legacy_table('tenant_retrieval_settings', 'tenant_id');

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

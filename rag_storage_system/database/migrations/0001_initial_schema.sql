-- Normalized schema for the Secure RAG Storage System.
--
-- Ported from the SQLite prototype (app/metadata/sqlite_repository.py)
-- to Postgres, and extended toward the full design: users, folders,
-- documents, document versions, chunks, embeddings, permissions,
-- analysis requests/reports, and audit logs.
--
-- Only `folders` and `documents` are wired up to application code
-- today (via app/metadata/postgres_repository.py) - the rest exist so
-- later features (real user accounts/RBAC, version history, the
-- vector_store/retrieval phase, RAG query tracking) aren't fighting
-- the schema when they arrive. Every statement is idempotent
-- (IF NOT EXISTS) - this file is applied on every
-- PostgresMetadataRepository startup, the same way the SQLite
-- repository re-runs CREATE TABLE IF NOT EXISTS on every init.


-- ---------------------------------------------------------------------
-- users - not populated yet (today's auth is a single shared admin
-- key, see app/security/auth.py). Exists so real accounts/RBAC can be
-- added later without a schema migration fight.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'admin',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------
-- folders - a category, possibly nested ("Contracts/2024"). `path` is
-- the full nested path and the natural key the application already
-- uses everywhere; `parent_id` is a real foreign key for anything
-- that wants to walk the tree relationally instead of by string
-- prefix.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS folders (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    path            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    parent_path     TEXT,
    parent_id       BIGINT REFERENCES folders(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_folders_parent_path ON folders(parent_path);
CREATE INDEX IF NOT EXISTS idx_folders_parent_id ON folders(parent_id);


-- ---------------------------------------------------------------------
-- documents - one row per stored file. `relative_path`
-- (category/filename) is the natural key the storage backend and
-- application already use. `current_version_id` will point at the
-- latest row in document_versions once versioning is wired up - a
-- plain column rather than a foreign key, since document_versions
-- references documents and a real FK back would be circular.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    folder_id           BIGINT REFERENCES folders(id) ON DELETE CASCADE,
    category            TEXT NOT NULL,
    filename            TEXT NOT NULL,
    relative_path       TEXT NOT NULL UNIQUE,
    extension           TEXT,
    size                BIGINT,
    sha256              TEXT,
    status              TEXT NOT NULL DEFAULT 'Uploaded',
    status_detail       TEXT,
    current_version_id  BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS idx_documents_folder_id ON documents(folder_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);


-- ---------------------------------------------------------------------
-- document_versions - not populated yet. Every replace/upload-over-
-- an-existing-file becomes a new row here once wired up, so history
-- survives instead of being overwritten in place the way `documents`
-- itself is today.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_versions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id     BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    size            BIGINT,
    sha256          TEXT,
    storage_path    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_number)
);


-- ---------------------------------------------------------------------
-- chunks / embeddings - not populated yet (Phases 4-5 currently write
-- to storage/chunks/ and storage/embeddings/ as JSON files - see
-- app/segmentation/chunker.py and app/embeddings/embedding_manager.py).
-- These mirror that same data in queryable form for whenever the
-- vector_store/retrieval phase needs to join back to documents/
-- folders instead of re-parsing JSON off disk. `embeddings.vector` is
-- a plain float array rather than a pgvector column - similarity
-- search is app/vector_store's job (not yet built), which may end up
-- using pgvector, Chroma, or something else entirely; this table
-- stays a durable, engine-agnostic record either way.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id         BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id            TEXT NOT NULL UNIQUE,
    segment_id          TEXT NOT NULL,
    chunk_index         INTEGER NOT NULL,
    start_page          INTEGER,
    end_page            INTEGER,
    chapter             TEXT,
    section             TEXT,
    subsection          TEXT,
    text                TEXT NOT NULL,
    word_count          INTEGER,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);

CREATE TABLE IF NOT EXISTS embeddings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_id        BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model_name      TEXT NOT NULL,
    dimension       INTEGER NOT NULL,
    vector          DOUBLE PRECISION[] NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, model_name)
);


-- ---------------------------------------------------------------------
-- permissions - not populated yet. Per-user access to a folder or a
-- specific document, for whenever app/security/access_control.py
-- moves beyond today's single shared admin key.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permissions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    folder_id       BIGINT REFERENCES folders(id) ON DELETE CASCADE,
    document_id     BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    permission_type TEXT NOT NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (folder_id IS NOT NULL OR document_id IS NOT NULL)
);


-- ---------------------------------------------------------------------
-- analysis_requests / analysis_reports - not populated yet. Tracking
-- for whatever RAG query/analysis layer eventually sits on top of
-- app/retrieval/ (a question asked against a document set, and the
-- report/answer produced from it).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_requests (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id     BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    requested_by    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    request_type    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    analysis_request_id    BIGINT NOT NULL REFERENCES analysis_requests(id) ON DELETE CASCADE,
    content                 JSONB NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------
-- audit_logs - mirrors logs/audit.log (app/security/audit_log.py) in
-- queryable form. Not wired up from Python yet - the file remains the
-- source of truth today; this table exists so a future dashboard or
-- report can query audit history with SQL instead of parsing JSONL.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "timestamp"     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL DEFAULT 'admin',
    action          TEXT NOT NULL,
    category        TEXT,
    filename        TEXT,
    status          TEXT NOT NULL,
    detail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs("timestamp");

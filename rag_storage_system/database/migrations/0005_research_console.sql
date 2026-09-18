-- 0005_research_console.sql
-- Phase 2 (Private Research Console).
--
-- Three concerns, one file:
--   system_prompts   the owner-editable, VERSIONED citation-lock prompt
--                    (Blueprint Phase 2 step 5: "not hard-coded")
--   research_threads persisted Q&A threads + their answers/sources
--   ask_query_logs   per-request observability (Work Plan Milestone 2)
--
-- Postgres-only, same as 0002/0004 - the SQLite metadata backend reads
-- 0001 only (app/metadata/sqlite_repository.py). The research console
-- needs Postgres regardless, because retrieval does.
-- Every statement is IF NOT EXISTS: these files are re-applied on every
-- startup by PostgresMetadataRepository and PgVectorRepository alike.

CREATE TABLE IF NOT EXISTS system_prompts (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    version     INTEGER      NOT NULL,
    content     TEXT         NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_by  VARCHAR(255),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);

-- At most one active version per prompt name. Rollback is "activate an
-- older version", never "edit in place" - so every version the owner has
-- ever saved stays readable and auditable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_prompts_one_active
    ON system_prompts (name) WHERE is_active;

CREATE TABLE IF NOT EXISTS research_threads (
    id          SERIAL PRIMARY KEY,
    owner_id    INTEGER      NOT NULL,
    title       TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_threads_owner
    ON research_threads (owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_messages (
    id               SERIAL PRIMARY KEY,
    thread_id        INTEGER NOT NULL
                     REFERENCES research_threads (id) ON DELETE CASCADE,
    role             VARCHAR(20) NOT NULL,   -- 'question' | 'answer'
    content          TEXT        NOT NULL,
    -- The structured source list behind an answer: filename, category,
    -- chapter, section, pages, chunk_id, score. Stored with the message
    -- so the source panel and any later export show exactly what was
    -- cited at the time, not what retrieval would return today.
    sources          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- 'verified' | 'stripped' | 'not_in_library'
    citation_status  VARCHAR(30),
    citation_detail  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_messages_thread
    ON research_messages (thread_id, id);

-- Work Plan Milestone 2, "Observability": log every request - query,
-- retrieved chunk IDs + scores, model, token usage, latency, and the
-- citation-check result - for the owner's audit and tuning. This is
-- what makes a citation-lock violation findable after the fact instead
-- of invisible.
CREATE TABLE IF NOT EXISTS ask_query_logs (
    id                SERIAL PRIMARY KEY,
    owner_id          INTEGER,
    thread_id         INTEGER,
    query             TEXT        NOT NULL,
    category          TEXT,
    retrieved         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    top_score         REAL,
    answered          BOOLEAN     NOT NULL DEFAULT FALSE,
    model             TEXT,
    prompt_version    INTEGER,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    latency_ms        INTEGER,
    citation_status   VARCHAR(30),
    citation_detail   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ask_query_logs_created
    ON ask_query_logs (created_at DESC);
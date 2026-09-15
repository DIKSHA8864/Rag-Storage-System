-- pgvector extension + a table to store each chunk's embedding vector
-- alongside enough metadata to make it independently queryable
-- (category, filename, chunk text) - see app/vector_store/vector_repository.py.
--
-- Applied idempotently (IF NOT EXISTS throughout), same as
-- 0001_initial_schema.sql - both PostgresMetadataRepository and
-- PgVectorRepository apply every file in this directory on startup,
-- so either one being constructed first is enough to get the schema
-- in place.
--
-- `document_id` here is the pipeline's own id - the filename stem
-- used throughout app/segmentation/ and app/embeddings/ (e.g.
-- "report" for "report.txt") - not documents.id from
-- 0001_initial_schema.sql. The two id spaces are different (a
-- pre-existing property of the chunking pipeline, not introduced
-- here), so this is a plain TEXT column, not a foreign key.
--
-- The vector column is fixed at 384 dimensions to match
-- EMBEDDING_MODEL's default (all-MiniLM-L6-v2) - the same coupling
-- app/segmentation/chunker.py's MAX_CHUNK_WORDS already has to this
-- exact model. Switching to a different-dimension model later needs
-- a new migration to alter this column.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_id        TEXT NOT NULL UNIQUE,
    document_id     TEXT NOT NULL,
    category        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    chunk_text      TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    embedding       vector(384) NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_document_id ON chunk_embeddings(document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_category ON chunk_embeddings(category);

-- Vector similarity search (cosine distance - the metric
-- sentence-transformers models are normally compared with).
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_embedding_hnsw
    ON chunk_embeddings USING hnsw (embedding vector_cosine_ops);

-- Keyword search (app/retrieval/search.py's keyword_search()).
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_text_fts
    ON chunk_embeddings USING gin (to_tsvector('english', chunk_text));

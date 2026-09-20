-- 0006_retrieval_settings.sql
-- Owner-editable retrieval settings (Top K, score threshold, minimum
-- chunks) used by the hybrid retrieval pipeline
-- (app/retrieval/retriever.py) - see app/retrieval_settings.py.
-- Single-row table: id is always 1.

CREATE TABLE IF NOT EXISTS retrieval_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    top_k INTEGER NOT NULL,
    score_threshold DOUBLE PRECISION NOT NULL,
    min_chunks INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255)
);

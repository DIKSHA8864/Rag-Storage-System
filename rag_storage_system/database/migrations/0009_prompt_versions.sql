-- 0009_prompt_versions.sql
-- Version history for the system prompts driving Claude-backed
-- narrative/answer generation (app/analysis/claude_narrative.py,
-- app/analysis/answer_generator.py) - lets an Owner roll out new
-- wording and roll back without a deploy.

CREATE TABLE IF NOT EXISTS prompt_versions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_active ON prompt_versions (name, is_active);
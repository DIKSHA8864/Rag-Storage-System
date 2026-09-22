-- 0014_llm_usage_log.sql
-- Per-call LLM usage/cost instrumentation (Milestone 7 - "cost
-- instrumentation per session"). One row per Claude API call, linked
-- to whichever session/matter it was made on behalf of, so cost can
-- be attributed and audited - see app/observability/usage_log.py.

CREATE TABLE IF NOT EXISTS llm_usage_log (
    id SERIAL PRIMARY KEY,
    matter_id INTEGER REFERENCES matters(id),
    intake_session_id INTEGER REFERENCES intake_sessions(id),
    purpose VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_matter ON llm_usage_log (matter_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_log_session ON llm_usage_log (intake_session_id);
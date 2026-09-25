-- Guided intake, flow version 2 (Blueprint Phase 3 / Work Plan M5): story
-- first, Claude follow-ups from the firm's question frameworks, the
-- owner-editable ancillary checklist, protected activity, key dates with
-- chronology validation, documents. Interviews started before this keep
-- flow_version 1 and finish on the old flow. Idempotent.

ALTER TABLE interview_state ADD COLUMN IF NOT EXISTS flow_version INTEGER NOT NULL DEFAULT 1;
-- Terms acceptance is recorded "with timestamp and IP" (Work Plan M5).
ALTER TABLE interview_state ADD COLUMN IF NOT EXISTS terms_accepted_ip VARCHAR(64);
-- Generated once after the story, so resuming asks the same questions.
ALTER TABLE interview_state ADD COLUMN IF NOT EXISTS follow_up_questions JSONB;
-- The checklist as it was when this interview started - an admin editing it
-- mid-interview must not shift the questions under an in-progress client.
ALTER TABLE interview_state ADD COLUMN IF NOT EXISTS checklist_snapshot JSONB;

-- The owner-editable ancillary-sweep checklist, per organization. No rows =
-- the built-in default (app/intake_engine/mandatory_sweep.py).
CREATE TABLE IF NOT EXISTS intake_checklist_questions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    key VARCHAR(60) NOT NULL,
    prompt_en TEXT NOT NULL,
    prompt_es TEXT NOT NULL,
    position INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255),
    UNIQUE (tenant_id, key)
);

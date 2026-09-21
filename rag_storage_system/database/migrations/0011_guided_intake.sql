-- 0011_guided_intake.sql
-- Guided Intake Engine: a conversational, state-machine-driven
-- interview layered on top of Phase 3's intake_sessions
-- (0010_intake_foundation.sql). One interview_state row per intake
-- session (language, terms acceptance timestamp, current state/step -
-- what makes the interview resumable), a full intake_messages
-- transcript, and intake_facts - the structured answers extracted
-- along the way (mandatory sweep, protected activity, the closing
-- narrative), consumed later by app/report/builder.py alongside
-- timeline_events.

CREATE TABLE IF NOT EXISTS interview_state (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL UNIQUE REFERENCES intake_sessions(id) ON DELETE CASCADE,
    language VARCHAR(5),
    terms_accepted_at TIMESTAMPTZ,
    terms_version VARCHAR(20),
    current_state VARCHAR(30) NOT NULL DEFAULT 'language_selection',
    current_step_index INTEGER NOT NULL DEFAULT 0,
    mandatory_sweep_completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS intake_messages (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('assistant', 'user')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intake_messages_session ON intake_messages (intake_session_id);

CREATE TABLE IF NOT EXISTS intake_facts (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    category VARCHAR(30) NOT NULL,
    fact_key VARCHAR(100) NOT NULL,
    fact_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intake_facts_session ON intake_facts (intake_session_id);
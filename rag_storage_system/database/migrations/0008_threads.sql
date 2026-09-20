-- 0008_threads.sql
-- Conversation history for POST /end-user/query/stream, isolated per
-- matter (see 0007_matters.sql) - see app/threads.py.

CREATE TABLE IF NOT EXISTS threads (
    id SERIAL PRIMARY KEY,
    matter_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_threads_matter ON threads (matter_id);

CREATE TABLE IF NOT EXISTS thread_messages (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    sources_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_thread_messages_thread ON thread_messages (thread_id);
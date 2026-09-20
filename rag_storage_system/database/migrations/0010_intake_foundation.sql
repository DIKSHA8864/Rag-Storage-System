-- 0010_intake_foundation.sql
-- Phase 3 foundation: Guided Client Intake + Multimodal Input
-- Processing + Report Generation. An intake_session is a Client's
-- (Matter's) resumable guided-intake session - optionally linked to a
-- Phase 2 thread (0008_threads.sql) for its Q&A history, but with its
-- own lifecycle so it can hold uploaded inputs, extracted content, a
-- timeline, and generated reports, none of which belong on a plain
-- Q&A thread.

CREATE TABLE IF NOT EXISTS intake_sessions (
    id SERIAL PRIMARY KEY,
    matter_id INTEGER NOT NULL REFERENCES matters(id),
    thread_id INTEGER REFERENCES threads(id),
    title VARCHAR(255) NOT NULL DEFAULT 'New intake',
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'abandoned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intake_sessions_matter ON intake_sessions (matter_id);

-- One row per file a Client uploaded to an intake session (a document,
-- image, audio, video, or a ZIP of any of those - app/multimodal/).
-- Stored under INTAKE_STORAGE_PATH, NEVER under ORIGINAL_STORAGE_PATH -
-- see app/storage/__init__.py's get_intake_storage_backend().
CREATE TABLE IF NOT EXISTS uploaded_inputs (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    original_filename VARCHAR(500) NOT NULL,
    stored_category VARCHAR(500) NOT NULL,
    stored_filename VARCHAR(500) NOT NULL,
    media_type VARCHAR(20) NOT NULL
        CHECK (media_type IN ('document', 'image', 'audio', 'video', 'archive')),
    size INTEGER NOT NULL,
    sha256 VARCHAR(64),
    processing_status VARCHAR(20) NOT NULL DEFAULT 'queued'
        CHECK (processing_status IN ('queued', 'processing', 'completed', 'failed', 'partial')),
    status_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_inputs_session ON uploaded_inputs (intake_session_id);

-- Text pulled out of an uploaded_input by app/multimodal/ - one row per
-- extracted piece. archive_member_filename is set when the source was
-- one member of a ZIP, so a ZIP's contents stay traceable individually.
-- `provider` records which OCR/STT/Vision implementation produced it
-- (including "mock") for full traceability - a report built from mock
-- output must never be presented as equivalent to a real extraction.
CREATE TABLE IF NOT EXISTS extracted_information (
    id SERIAL PRIMARY KEY,
    uploaded_input_id INTEGER NOT NULL REFERENCES uploaded_inputs(id) ON DELETE CASCADE,
    archive_member_filename VARCHAR(500),
    content_type VARCHAR(20) NOT NULL
        CHECK (content_type IN ('text', 'ocr_text', 'transcript', 'caption')),
    text TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    is_mock BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_extracted_information_input ON extracted_information (uploaded_input_id);

-- Full audit trail of an intake session - every upload, every
-- processing state change, every report generated.
CREATE TABLE IF NOT EXISTS timeline_events (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeline_events_session ON timeline_events (intake_session_id);

-- One row per generated report (app/report/) - the rendered file
-- itself lives in the intake storage backend ("reports" category);
-- this row is its index: which format, which session, when.
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    format VARCHAR(10) NOT NULL CHECK (format IN ('docx', 'pdf', 'image')),
    stored_category VARCHAR(500) NOT NULL,
    stored_filename VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_session ON reports (intake_session_id);

-- 0013_matter_workspace.sql
-- Matter Workspace: direct Matter <-> Uploaded Documents / Reports
-- links (for role-based access checks that only have a report_id/
-- upload_id, not the Matter's own key), and matter_assignments -
-- which firm staff (Owner-side accounts, app/security/owner_repository.py)
-- may act on which Matter. A row here is what makes an 'attorney' or
-- 'paralegal' role (see 0004_owners.sql's owners.role) mean anything -
-- without an assignment, they can access no Matter at all. An owner
-- with role='owner' bypasses this table entirely (see
-- app/security/auth.py's ensure_matter_access()).

ALTER TABLE uploaded_inputs ADD COLUMN IF NOT EXISTS matter_id INTEGER REFERENCES matters(id);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS matter_id INTEGER REFERENCES matters(id);

UPDATE uploaded_inputs u SET matter_id = s.matter_id
    FROM intake_sessions s WHERE u.intake_session_id = s.id AND u.matter_id IS NULL;
UPDATE reports r SET matter_id = s.matter_id
    FROM intake_sessions s WHERE r.intake_session_id = s.id AND r.matter_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_uploaded_inputs_matter ON uploaded_inputs (matter_id);
CREATE INDEX IF NOT EXISTS idx_reports_matter ON reports (matter_id);

CREATE TABLE IF NOT EXISTS matter_assignments (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    matter_id INTEGER NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('attorney', 'paralegal')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, matter_id)
);

CREATE INDEX IF NOT EXISTS idx_matter_assignments_owner ON matter_assignments (owner_id);
CREATE INDEX IF NOT EXISTS idx_matter_assignments_matter ON matter_assignments (matter_id);

-- Part 3 (Complaint Generator) tables - added here rather than a
-- separate migration since both are Phase 4 foundation applied in one
-- deploy together.

CREATE TABLE IF NOT EXISTS cause_of_action_library (
    id SERIAL PRIMARY KEY,
    category VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    elements JSONB NOT NULL,
    authority_citation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cause_of_action_library_category ON cause_of_action_library (category);

CREATE TABLE IF NOT EXISTS complaints (
    id SERIAL PRIMARY KEY,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    matter_id INTEGER NOT NULL REFERENCES matters(id),
    format VARCHAR(10) NOT NULL CHECK (format IN ('docx', 'pdf')),
    cause_of_action_ids JSONB NOT NULL,
    stored_category VARCHAR(500) NOT NULL,
    stored_filename VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_complaints_session ON complaints (intake_session_id);
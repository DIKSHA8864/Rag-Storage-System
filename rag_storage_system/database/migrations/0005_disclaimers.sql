-- 0005_disclaimers.sql
-- Owner-editable disclaimer shown on every DOCX/PDF analysis report
-- export (see app/disclaimer.py, app/analysis/report_export.py).
-- Single-row table: id is always 1.

CREATE TABLE IF NOT EXISTS disclaimer (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    text TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255)
);

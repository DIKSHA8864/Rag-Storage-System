-- 0012_report_review_queue.sql
-- Owner review queue for Client-intake reports (app/report/) - every
-- generated report starts 'pending_review' and must be approved by
-- the Owner/attorney before an End User can download it (see
-- app/api/intake_api.py's download gate and app/api/storage_api.py's
-- GET /admin/reports/pending, POST /admin/reports/{id}/approve|reject).

CREATE TABLE IF NOT EXISTS report_reviews (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL UNIQUE REFERENCES reports(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'approved', 'rejected')),
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_reviews_status ON report_reviews (status);
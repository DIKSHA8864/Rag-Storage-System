-- California pleading paper and the firm's own .docx templates (Blueprint
-- Phase 4). Idempotent.

-- What goes in the attorney block and caption of every generated pleading,
-- per organization. Blank fields are left as bracketed placeholders.
CREATE TABLE IF NOT EXISTS tenant_pleading_settings (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    attorney_name VARCHAR(255) NOT NULL DEFAULT '',
    bar_number VARCHAR(50) NOT NULL DEFAULT '',
    firm_name VARCHAR(255) NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    phone VARCHAR(50) NOT NULL DEFAULT '',
    email VARCHAR(255) NOT NULL DEFAULT '',
    attorney_for VARCHAR(255) NOT NULL DEFAULT '',
    court_name VARCHAR(255) NOT NULL DEFAULT '',
    county VARCHAR(100) NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255)
);

-- The firm's own Word templates with {{placeholders}}; the generated text
-- goes where {{body}} is.
CREATE TABLE IF NOT EXISTS document_templates (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(30) NOT NULL DEFAULT 'complaint',
    original_filename VARCHAR(255) NOT NULL,
    stored_category VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    placeholders JSONB NOT NULL DEFAULT '[]',
    uploaded_by VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_document_templates_tenant ON document_templates (tenant_id, kind);

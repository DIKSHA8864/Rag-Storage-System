-- Each organization's own Dropbox connection for vault sync, set up by the
-- owner on the Vault page ("Connect Dropbox" + the folders to sync) instead
-- of server settings. The refresh token is stored encrypted
-- (app/security/secret_box.py). Idempotent.
SELECT rag_retire_legacy_table('dropbox_connections', 'refresh_token_encrypted');

CREATE TABLE IF NOT EXISTS dropbox_connections (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    account_id VARCHAR(255) NOT NULL,
    account_name VARCHAR(255),
    account_email VARCHAR(255),
    refresh_token_encrypted TEXT NOT NULL,
    folders_json TEXT NOT NULL DEFAULT '[]',   -- Dropbox folder paths (path_display) to sync
    connected_by VARCHAR(255),
    connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(255),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

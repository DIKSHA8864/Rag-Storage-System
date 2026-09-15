"""
Tests for the audit log (app/security/audit_log.py) and its wiring
into the admin API's upload/replace/delete/rename endpoints.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security import audit_log
from app.storage.local_backend import LocalStorageBackend


def _read_entries(log_path):
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------
# log_audit_event() unit tests
# ---------------------------------------------------------------------


def test_log_audit_event_appends_json_line(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "audit.log"

    settings = audit_log.get_settings()
    monkeypatch.setattr(settings, "audit_log_path", str(log_path))

    audit_log.log_audit_event("upload", category="Docs", filename="a.txt")
    audit_log.log_audit_event("delete_document", category="Docs", filename="a.txt")

    entries = _read_entries(log_path)
    assert len(entries) == 2
    assert entries[0]["action"] == "upload"
    assert entries[0]["category"] == "Docs"
    assert entries[0]["filename"] == "a.txt"
    assert entries[0]["actor"] == "admin"
    assert "timestamp" in entries[0]
    assert entries[1]["action"] == "delete_document"


def test_log_audit_event_never_raises_on_unwritable_path(tmp_path, monkeypatch):
    # A plain file sitting where a directory needs to go: mkdir(parents=True)
    # fails on every OS this way, without relying on OS-specific paths
    # like /dev/null.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    settings = audit_log.get_settings()
    monkeypatch.setattr(settings, "audit_log_path", str(blocker / "audit.log"))

    audit_log.log_audit_event("upload", category="Docs", filename="a.txt")  # must not raise


# ---------------------------------------------------------------------
# Wiring into the API
# ---------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    backend = LocalStorageBackend(
        originals_dir=tmp_path / "originals",
        quarantine_dir=tmp_path / "quarantine",
    )
    repository = SQLiteMetadataRepository(tmp_path / "metadata.db")
    log_path = tmp_path / "logs" / "audit.log"

    monkeypatch.setattr(storage_api, "storage_backend", backend)
    monkeypatch.setattr(storage_api, "metadata_repository", repository)
    monkeypatch.setattr(audit_log.get_settings(), "audit_log_path", str(log_path))

    return TestClient(storage_api.app), log_path


def test_upload_is_audited(client):
    test_client, log_path = client

    test_client.post(
        "/categories/Docs/documents",
        files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    entries = _read_entries(log_path)
    assert any(e["action"] == "upload" and e["status"] == "success" for e in entries)


def test_rejected_upload_is_still_audited(client):
    test_client, log_path = client

    test_client.post(
        "/categories/Docs/documents",
        files={"file": ("malware.exe", io.BytesIO(b"data"), "application/octet-stream")},
    )

    entries = _read_entries(log_path)
    assert any(e["action"] == "upload" and e["status"] == "rejected" for e in entries)


def test_delete_document_is_audited(client):
    test_client, log_path = client

    test_client.post(
        "/categories/Docs/documents",
        files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    test_client.delete("/categories/Docs/documents/report.txt")

    entries = _read_entries(log_path)
    assert any(e["action"] == "delete_document" and e["status"] == "success" for e in entries)


def test_rename_category_is_audited(client):
    test_client, log_path = client

    test_client.post("/categories", json={"name": "Old"})
    test_client.patch("/categories/Old", json={"new_name": "New"})

    entries = _read_entries(log_path)
    assert any(e["action"] == "rename_category" and e["status"] == "success" for e in entries)


def test_delete_category_is_audited(client):
    test_client, log_path = client

    test_client.post("/categories", json={"name": "Empty"})
    test_client.delete("/categories/Empty")

    entries = _read_entries(log_path)
    assert any(e["action"] == "delete_category" and e["status"] == "success" for e in entries)

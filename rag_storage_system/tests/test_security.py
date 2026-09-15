"""
Security tests: path-sanitization guarantees (app/security/path_security)
plus an end-to-end check that the admin API can never be tricked into
writing outside protected storage via a crafted category/filename.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.path_security import (
    resolve_within,
    sanitize_category_path,
    sanitize_path_segment,
)
from app.storage.local_backend import LocalStorageBackend


# ---------------------------------------------------------------------
# sanitize_category_path()
# ---------------------------------------------------------------------


def test_sanitize_category_path_keeps_plain_nesting():
    assert sanitize_category_path("Contracts/2024") == "Contracts/2024"


def test_sanitize_category_path_strips_traversal_segments():
    assert sanitize_category_path("Contracts/../../etc") == "Contracts/etc"


def test_sanitize_category_path_normalizes_backslashes():
    assert sanitize_category_path("Contracts\\2024") == "Contracts/2024"


def test_sanitize_category_path_all_unsafe_falls_back():
    assert sanitize_category_path("../..") == "uncategorized"


def test_sanitize_category_path_empty_falls_back():
    assert sanitize_category_path("") == "uncategorized"


def test_sanitize_category_path_drops_empty_segments():
    assert sanitize_category_path("Contracts//2024") == "Contracts/2024"


# ---------------------------------------------------------------------
# resolve_within() with nested segments (the shape LocalStorageBackend
# now uses for every category-related path)
# ---------------------------------------------------------------------


def test_resolve_within_allows_multi_segment_nesting(tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    result = resolve_within(base, *"Contracts/2024".split("/"), "file.txt")
    assert base in result.parents


def test_resolve_within_blocks_multi_segment_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    with pytest.raises(ValueError):
        resolve_within(base, *"../../../../etc/passwd".split("/"))


# ---------------------------------------------------------------------
# End-to-end: a hostile category/filename can never escape storage,
# even once it reaches the API.
# ---------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    backend = LocalStorageBackend(
        originals_dir=tmp_path / "originals",
        quarantine_dir=tmp_path / "quarantine",
    )
    repository = SQLiteMetadataRepository(tmp_path / "metadata.db")

    monkeypatch.setattr(storage_api, "storage_backend", backend)
    monkeypatch.setattr(storage_api, "metadata_repository", repository)

    return TestClient(storage_api.app), backend, tmp_path


def test_upload_with_traversal_category_stays_inside_storage(client):
    test_client, backend, tmp_path = client

    response = test_client.post(
        "/categories/..%2F..%2Fetc/documents",
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 200
    # Nothing was written outside the sandboxed originals directory.
    assert not (tmp_path / "etc").exists()
    assert not (tmp_path.parent / "etc").exists()


def test_upload_with_traversal_filename_is_sanitized(client):
    test_client, backend, tmp_path = client

    response = test_client.post(
        "/categories/Docs/documents",
        files={"file": ("../../evil.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 200
    stored_filename = response.json()["results"][0]["filename"]
    assert "/" not in stored_filename
    assert (backend.originals_dir / "Docs" / stored_filename).exists()


def test_upload_rejects_disallowed_extension_to_quarantine(client):
    test_client, backend, _ = client

    response = test_client.post(
        "/categories/Docs/documents",
        files={"file": ("payload.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
    )

    body = response.json()
    assert body["results"][0]["status"] == "rejected"
    assert (backend.quarantine_dir / "Docs" / "payload.exe").exists()
    assert not (backend.originals_dir / "Docs" / "payload.exe").exists()

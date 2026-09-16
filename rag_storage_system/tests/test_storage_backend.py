"""
Tests for the storage backend abstraction (app/storage) and the
path-sanitization helpers it relies on (app/security/path_security).

Every test below runs against BOTH backends via the parametrized
`backend` fixture - LocalStorageBackend always, and S3StorageBackend
when MinIO is up. That's the point of the StorageBackend interface:
if the same contract tests pass against both, the two really are
interchangeable and app/api/storage_api.py cannot tell them apart.

The S3 pass is skipped unless RUN_S3_TESTS=1, so the default
`pytest tests/` still needs nothing running:

    docker compose up -d
    RUN_S3_TESTS=1 pytest tests/test_storage_backend.py -q
"""

import io
import os
import uuid

import pytest

from app.security.path_security import resolve_within, sanitize_path_segment
from app.storage.local_backend import LocalStorageBackend


@pytest.fixture(params=["local", "s3"])
def backend(request, tmp_path):
    if request.param == "local":
        return LocalStorageBackend(
            originals_dir=tmp_path / "originals",
            quarantine_dir=tmp_path / "quarantine",
        )

    if os.environ.get("RUN_S3_TESTS") != "1":
        pytest.skip("Set RUN_S3_TESTS=1 with MinIO running to test the S3 backend.")

    from app.storage.s3_backend import S3StorageBackend

    # Fresh buckets per test: an object store has no tmp_path
    # equivalent, and these tests must not see each other's objects.
    suffix = uuid.uuid4().hex[:12]

    return S3StorageBackend(
        bucket=f"test-{suffix}",
        quarantine_bucket=f"test-q-{suffix}",
        region=os.environ.get("S3_REGION", "us-east-1"),
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000"),
        access_key_id=os.environ.get("S3_ACCESS_KEY_ID", "ragminio"),
        secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", "ragminio123"),
    )


# ---------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------


def test_sanitize_strips_traversal_sequences():
    assert sanitize_path_segment("../../etc") == "etc"
    assert sanitize_path_segment("..") == "unnamed"
    assert sanitize_path_segment("a/b\\c") == "a_b_c"


def test_resolve_within_blocks_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    with pytest.raises(ValueError):
        resolve_within(base, "..", "..", "etc", "passwd")


def test_resolve_within_allows_nested_path(tmp_path):
    base = tmp_path / "base"
    base.mkdir()

    result = resolve_within(base, "sub", "file.txt")
    assert base in result.parents


# ---------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------


def test_create_and_list_category(backend):
    name = backend.create_category("Contracts")
    assert name == "Contracts"

    categories = backend.list_categories()
    assert categories == [{"name": "Contracts", "document_count": 0}]


def test_create_category_sanitizes_traversal(backend):
    name = backend.create_category("../../etc")
    assert name == "etc"
    # A plain category named "etc" inside storage - never a path that
    # climbed out to the real /etc. Asserted through the interface so
    # this holds for object stores too, which have no filesystem path
    # to inspect.
    assert {c["name"] for c in backend.list_categories()} == {"etc"}


def test_rename_category(backend):
    backend.create_category("Old")
    new_name = backend.rename_category("Old", "New")

    assert new_name == "New"
    names = {c["name"] for c in backend.list_categories()}
    assert names == {"New"}


def test_rename_category_conflict_raises(backend):
    backend.create_category("A")
    backend.create_category("B")

    with pytest.raises(ValueError):
        backend.rename_category("A", "B")


def test_rename_missing_category_raises(backend):
    with pytest.raises(FileNotFoundError):
        backend.rename_category("DoesNotExist", "New")


def test_delete_empty_category(backend):
    backend.create_category("Empty")
    assert backend.delete_category("Empty") is True
    assert backend.list_categories() == []


def test_delete_nonempty_category_requires_force(backend):
    backend.create_category("Full")
    backend.save("Full", "a.txt", io.BytesIO(b"hello"))

    with pytest.raises(ValueError):
        backend.delete_category("Full")

    # still there
    assert backend.list_categories()[0]["document_count"] == 1

    assert backend.delete_category("Full", force=True) is True
    assert backend.list_categories() == []


def test_delete_missing_category_returns_false(backend):
    assert backend.delete_category("Nope") is False


# ---------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------


def test_save_and_list_file(backend):
    backend.create_category("Docs")
    result = backend.save("Docs", "report.txt", io.BytesIO(b"hello world"))

    assert result["stored_filename"] == "report.txt"
    assert result["size"] == 11
    assert len(result["sha256"]) == 64

    files = backend.list_files("Docs")
    assert len(files) == 1
    assert files[0]["filename"] == "report.txt"


def test_save_avoids_overwriting_existing_file(backend):
    backend.create_category("Docs")
    backend.save("Docs", "report.txt", io.BytesIO(b"first"))
    result = backend.save("Docs", "report.txt", io.BytesIO(b"second"))

    assert result["stored_filename"] == "report_1.txt"
    assert {f["filename"] for f in backend.list_files("Docs")} == {
        "report.txt",
        "report_1.txt",
    }


def test_replace_updates_contents_same_name(backend):
    backend.create_category("Docs")
    backend.save("Docs", "report.txt", io.BytesIO(b"old content"))

    result = backend.replace("Docs", "report.txt", io.BytesIO(b"new content!!"))

    assert result["stored_filename"] == "report.txt"
    with backend.open_file("Docs", "report.txt") as f:
        assert f.read() == b"new content!!"


def test_replace_missing_file_raises(backend):
    backend.create_category("Docs")

    with pytest.raises(FileNotFoundError):
        backend.replace("Docs", "missing.txt", io.BytesIO(b"data"))


def test_delete_file(backend):
    backend.create_category("Docs")
    backend.save("Docs", "report.txt", io.BytesIO(b"data"))

    assert backend.delete("Docs", "report.txt") is True
    assert backend.list_files("Docs") == []


def test_delete_missing_file_returns_false(backend):
    backend.create_category("Docs")
    assert backend.delete("Docs", "missing.txt") is False


def test_exists(backend):
    backend.create_category("Docs")
    assert backend.exists("Docs", "report.txt") is False

    backend.save("Docs", "report.txt", io.BytesIO(b"data"))
    assert backend.exists("Docs", "report.txt") is True


def test_filename_traversal_is_sanitized_on_save(backend):
    backend.create_category("Docs")
    result = backend.save("Docs", "../../evil.txt", io.BytesIO(b"data"))

    # sanitized to a plain filename, stored safely inside the category
    assert "/" not in result["stored_filename"]
    assert result["category"] == "Docs"
    assert backend.exists("Docs", result["stored_filename"])


# ---------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------


def test_quarantine_stores_outside_protected_storage(backend):
    result = backend.quarantine("Docs", "bad.exe", io.BytesIO(b"MZ..."))

    assert result["stored_filename"] == "bad.exe"
    assert result["category"] == "Docs"

    # The point of quarantine: it must NOT be reachable through
    # protected storage - not listed, and not retrievable.
    assert backend.list_files("Docs") == []
    assert backend.exists("Docs", "bad.exe") is False


# ---------------------------------------------------------------------
# Pre-signed URLs
# ---------------------------------------------------------------------


def test_presigned_urls(backend):
    """
    Object stores issue a time-limited signed URL; local disk has no
    URL space of its own and must say so explicitly rather than
    returning something that doesn't work.
    """

    backend.create_category("Docs")
    backend.save("Docs", "report.txt", io.BytesIO(b"data"))

    if isinstance(backend, LocalStorageBackend):
        with pytest.raises(NotImplementedError):
            backend.presigned_download_url("Docs", "report.txt")
        with pytest.raises(NotImplementedError):
            backend.presigned_upload_url("Docs", "report.txt")
        return

    download_url = backend.presigned_download_url("Docs", "report.txt")
    upload_url = backend.presigned_upload_url("Docs", "new.txt")

    for url in (download_url, upload_url):
        assert url.startswith("http")
        # Signed, and time-limited - not a bare public object URL.
        assert "X-Amz-Signature" in url
        assert "X-Amz-Expires" in url

    assert "Docs/report.txt" in download_url
    assert "Docs/new.txt" in upload_url

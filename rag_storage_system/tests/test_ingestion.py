"""
Ingestion tests (Phase 2), porting the manual checks
scripts/test_ingestion.py used to only print, into real assertions.
"""

import pytest

from app.ingestion import ingestion_manager
from app.ingestion.file_scanner import scan_path
from app.ingestion.file_validator import validate_file, validate_file_object
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.storage.local_backend import LocalStorageBackend
from config.settings import get_settings

MAX_FILE_SIZE = get_settings().max_file_size_bytes


# ---------------------------------------------------------------------
# file_validator
# ---------------------------------------------------------------------


def test_validate_file_accepts_supported_extension(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("content", encoding="utf-8")

    is_valid, reason = validate_file(path)
    assert (is_valid, reason) == (True, "valid")


def test_validate_file_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "doc.exe"
    path.write_text("content", encoding="utf-8")

    is_valid, reason = validate_file(path)
    assert is_valid is False
    assert reason.startswith("unsupported_extension")


def test_validate_file_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")

    is_valid, reason = validate_file(path)
    assert (is_valid, reason) == (False, "empty_file")


def test_validate_file_rejects_missing_file(tmp_path):
    is_valid, reason = validate_file(tmp_path / "missing.txt")
    assert (is_valid, reason) == (False, "file_not_found")


def test_validate_file_object_rejects_oversized_file():
    is_valid, reason = validate_file_object("big.pdf", MAX_FILE_SIZE + 1)
    assert (is_valid, reason) == (False, "file_too_large")


def test_validate_file_object_accepts_boundary_size():
    is_valid, reason = validate_file_object("big.pdf", MAX_FILE_SIZE)
    assert (is_valid, reason) == (True, "valid")


# ---------------------------------------------------------------------
# file_scanner
# ---------------------------------------------------------------------


def test_scan_path_splits_valid_and_rejected(tmp_path):
    (tmp_path / "good.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "bad.exe").write_text("hello", encoding="utf-8")

    valid_files, rejected_files = scan_path(str(tmp_path))

    assert [p.name for p in valid_files] == ["good.txt"]
    assert len(rejected_files) == 1
    assert rejected_files[0]["reason"].startswith("unsupported_extension")


def test_scan_path_recurses_into_subfolders(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "deep.txt").write_text("hello", encoding="utf-8")

    valid_files, _ = scan_path(str(tmp_path))
    assert [p.name for p in valid_files] == ["deep.txt"]


def test_scan_path_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_path(str(tmp_path / "does_not_exist"))


# ---------------------------------------------------------------------
# ingestion_manager.ingest() - routes through the storage backend and
# metadata repository, same as the upload API.
# ---------------------------------------------------------------------


@pytest.fixture
def isolated_ingest(tmp_path, monkeypatch):
    """Point ingest() at a throwaway storage backend + metadata db."""

    backend = LocalStorageBackend(
        originals_dir=tmp_path / "originals",
        quarantine_dir=tmp_path / "quarantine",
    )
    repository = SQLiteMetadataRepository(tmp_path / "metadata.db")

    monkeypatch.setattr(ingestion_manager, "get_storage_backend", lambda: backend)
    monkeypatch.setattr(ingestion_manager, "get_metadata_repository", lambda: repository)

    return backend, repository


def test_ingest_stores_valid_files_and_records_metadata(tmp_path, isolated_ingest):
    backend, repository = isolated_ingest

    source = tmp_path / "source"
    source.mkdir()
    (source / "report.txt").write_text("hello", encoding="utf-8")
    (source / "malware.exe").write_text("hello", encoding="utf-8")

    result = ingestion_manager.ingest(str(source))

    assert result["total_stored"] == 1
    assert result["total_rejected"] == 1
    assert backend.exists("uncategorized", "report.txt")

    documents = repository.list_documents()
    assert len(documents) == 1
    assert documents[0]["status"] == "Uploaded"


def test_ingest_preserves_folder_structure_as_categories(tmp_path, isolated_ingest):
    backend, repository = isolated_ingest

    source = tmp_path / "source"
    (source / "Contracts" / "2024").mkdir(parents=True)
    (source / "Contracts" / "2024" / "agreement.txt").write_text("hi", encoding="utf-8")

    result = ingestion_manager.ingest(str(source))

    assert result["total_stored"] == 1
    assert result["successful"][0]["category"] == "Contracts/2024"
    assert backend.exists("Contracts/2024", "agreement.txt")

    documents = repository.list_documents("Contracts/2024")
    assert len(documents) == 1


def test_ingest_single_file_uses_uncategorized(tmp_path, isolated_ingest):
    backend, _ = isolated_ingest

    single_file = tmp_path / "solo.txt"
    single_file.write_text("hi", encoding="utf-8")

    result = ingestion_manager.ingest(str(single_file))

    assert result["total_stored"] == 1
    assert backend.exists("uncategorized", "solo.txt")

"""
Contract tests for the metadata repository interface
(app/metadata/base.py), run against both implementations:

- SQLiteMetadataRepository - always runs, no external dependency.
- PostgresMetadataRepository - runs against rag_storage_test, a
  separate database on the real docker-compose Postgres server (see
  tests/postgres_test_support.py) if it's reachable, otherwise these
  cases are skipped (not failed) so the suite stays runnable without
  Docker. Never the real rag_storage database - these tests TRUNCATE.

Both backends must satisfy the exact same behavior - that's the point
of the interface - so every test below runs unchanged against
whichever backend the `repo` fixture hands it.
"""

import pytest

from app.metadata.models import DocumentStatus
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from tests.postgres_test_support import TEST_DSN, postgres_reachable


def _make_postgres_repo():
    from app.metadata.postgres_repository import PostgresMetadataRepository

    repo = PostgresMetadataRepository(TEST_DSN)
    # Isolate this test from whatever any other test/run left behind -
    # a real server persists data between tests, unlike a fresh
    # tmp_path SQLite file.
    with repo._connect() as conn:
        conn.execute("TRUNCATE documents, folders RESTART IDENTITY CASCADE")
    return repo


@pytest.fixture(params=["sqlite", "postgres"])
def repo(request, tmp_path):
    if request.param == "sqlite":
        return SQLiteMetadataRepository(tmp_path / "metadata.db")

    if not postgres_reachable():
        pytest.skip("Postgres not reachable at localhost:5432 (docker compose up -d)")

    return _make_postgres_repo()


# ---------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------


def test_create_folder_also_creates_ancestors(repo):
    repo.create_folder("Contracts/2024/Signed")

    names = {f["name"] for f in repo.list_folders()}
    assert names == {"Contracts", "Contracts/2024", "Contracts/2024/Signed"}


def test_list_folders_reports_document_count_including_descendants(repo):
    repo.create_folder("Contracts/2024")
    repo.upsert_document("Contracts/2024", "a.txt", ".txt", 10, "sha-a")
    repo.upsert_document("Contracts", "b.txt", ".txt", 10, "sha-b")

    counts = {f["name"]: f["document_count"] for f in repo.list_folders()}
    assert counts["Contracts/2024"] == 1
    assert counts["Contracts"] == 2  # includes the nested document


def test_rename_folder_moves_descendant_folders_and_documents(repo):
    repo.create_folder("Contracts/2024")
    repo.upsert_document("Contracts/2024", "a.txt", ".txt", 10, "sha-a")

    repo.rename_folder("Contracts", "Agreements")

    names = {f["name"] for f in repo.list_folders()}
    assert "Agreements" in names
    assert "Agreements/2024" in names
    assert "Contracts" not in names

    documents = repo.list_documents("Agreements/2024")
    assert len(documents) == 1
    assert documents[0]["relative_path"] == "Agreements/2024/a.txt"


def test_delete_folder_cascades_to_documents_and_subfolders(repo):
    repo.create_folder("Contracts/2024")
    repo.upsert_document("Contracts/2024", "a.txt", ".txt", 10, "sha-a")

    repo.delete_folder("Contracts")

    assert repo.list_folders() == []
    assert repo.list_documents() == []


# ---------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------


def test_upsert_document_then_get(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 123, "abc123")

    document = repo.get_document("Docs", "report.txt")
    assert document["size"] == 123
    assert document["sha256"] == "abc123"
    assert document["status"] == DocumentStatus.UPLOADED.value


def test_upsert_document_updates_existing_row_in_place(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 100, "old-hash")
    repo.upsert_document("Docs", "report.txt", ".txt", 200, "new-hash")

    documents = repo.list_documents("Docs")
    assert len(documents) == 1
    assert documents[0]["size"] == 200
    assert documents[0]["sha256"] == "new-hash"


def test_delete_document(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")
    assert repo.delete_document("Docs", "report.txt") is True
    assert repo.get_document("Docs", "report.txt") is None
    assert repo.delete_document("Docs", "report.txt") is False


def test_list_documents_filters_by_category_including_nested(repo):
    repo.upsert_document("Contracts", "top.txt", ".txt", 10, "a")
    repo.upsert_document("Contracts/2024", "nested.txt", ".txt", 10, "b")
    repo.upsert_document("Other", "other.txt", ".txt", 10, "c")

    names = {d["filename"] for d in repo.list_documents("Contracts")}
    assert names == {"top.txt", "nested.txt"}


def test_update_document_status(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")
    repo.update_document_status("Docs", "report.txt", DocumentStatus.PROCESSING.value)

    document = repo.get_document("Docs", "report.txt")
    assert document["status"] == DocumentStatus.PROCESSING.value


def test_update_document_status_with_detail_on_failure(repo):
    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")
    repo.update_document_status(
        "Docs", "report.txt", DocumentStatus.FAILED.value, status_detail="bad pdf"
    )

    document = repo.get_document("Docs", "report.txt")
    assert document["status"] == DocumentStatus.FAILED.value
    assert document["status_detail"] == "bad pdf"


def test_update_status_where_bulk_transitions(repo):
    repo.upsert_document("Docs", "a.txt", ".txt", 10, "a", status=DocumentStatus.PROCESSING.value)
    repo.upsert_document("Docs", "b.txt", ".txt", 10, "b", status=DocumentStatus.PROCESSING.value)
    repo.upsert_document("Docs", "c.txt", ".txt", 10, "c", status=DocumentStatus.UPLOADED.value)

    updated = repo.update_status_where(
        DocumentStatus.PROCESSING.value, DocumentStatus.INDEXED.value
    )

    assert updated == 2
    statuses = {d["filename"]: d["status"] for d in repo.list_documents("Docs")}
    assert statuses["a.txt"] == DocumentStatus.INDEXED.value
    assert statuses["b.txt"] == DocumentStatus.INDEXED.value
    assert statuses["c.txt"] == DocumentStatus.UPLOADED.value


def test_repository_sees_data_written_by_another_instance(repo, tmp_path):
    """
    Two separate repository instances pointed at the same underlying
    storage must see the same data - a fresh SQLiteMetadataRepository
    re-opening the same file, or a second PostgresMetadataRepository
    connecting to the same live server.
    """

    repo.upsert_document("Docs", "report.txt", ".txt", 10, "abc")

    if isinstance(repo, SQLiteMetadataRepository):
        other = SQLiteMetadataRepository(repo.db_path)
    else:
        from app.metadata.postgres_repository import PostgresMetadataRepository

        other = PostgresMetadataRepository(repo.dsn)

    assert other.get_document("Docs", "report.txt") is not None


# ---------------------------------------------------------------------
# Intake extracted content
# ---------------------------------------------------------------------


@pytest.mark.parametrize("content_type", ["text", "ocr_text", "transcript", "caption", "frame_caption"])
def test_every_extracted_content_type_the_pipeline_produces_can_be_stored(repo, content_type):
    """
    Regression: Postgres' CHECK constraint on extracted_information
    once omitted "frame_caption" (video frame analysis), so every video
    upload failed there while SQLite-only tests stayed green. Runs on
    both backends for exactly that reason.
    """

    import uuid

    matter = repo.create_matter("Intake Matter", f"hash-{uuid.uuid4().hex}")
    session = repo.create_intake_session(matter["id"], "Intake")
    uploaded = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=matter["id"], original_filename="clip.mp4",
        stored_category="c", stored_filename="clip.mp4", media_type="video", size=1, sha256=None,
    )

    repo.add_extracted_information(
        uploaded_input_id=uploaded["id"], content_type=content_type, text="[1.5s] A person at a desk.",
        provider="mock", is_mock=True,
    )

    assert [row["content_type"] for row in repo.list_extracted_information(uploaded["id"])] == [content_type]

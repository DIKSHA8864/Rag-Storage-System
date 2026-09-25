"""
The library search index must always match the library itself
(Blueprint acceptance Test 6 - "add, revise, and delete a vault file ->
the index reflects each change"): a deleted file's text is never
citable again, a replaced file never keeps chunks from its old version,
a renamed/moved folder doesn't leave duplicates, and two same-named
files in different folders never overwrite each other's chunks.

Drives the real HTTP endpoints and the real processing job
(app/jobs/processing.py - extraction, segmentation, chunking), with a
deterministic stand-in for the embedding model and conftest.py's
in-memory vector store (same semantics as PgVectorRepository - the SQL
itself is covered against real Postgres in tests/test_vector_store.py).
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.storage.local_backend import LocalStorageBackend


class _HashEmbedder:
    """Deterministic 384-dim vectors - no model download."""

    def embed(self, texts):
        return [[b / 255 for b in (hashlib.sha256(t.encode()).digest() * 12)] for t in texts]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.embeddings import embedding_manager
    from app.extraction import extractor_manager
    from app.segmentation import chunker, segmentation_manager

    monkeypatch.setattr(storage_api, "storage_backend", LocalStorageBackend(
        originals_dir=tmp_path / "originals", quarantine_dir=tmp_path / "quarantine",
    ))
    monkeypatch.setattr(storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db"))

    monkeypatch.setattr(extractor_manager, "ORIGINALS_DIR", tmp_path / "originals")
    monkeypatch.setattr(extractor_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(embedding_manager, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(embedding_manager, "EMBEDDINGS_DIR", tmp_path / "embeddings")
    monkeypatch.setattr(embedding_manager, "get_embedding_provider", lambda model_name=None: _HashEmbedder())

    return TestClient(storage_api.app)


def _upload(client, category, filename, text):
    response = client.post(
        f"/categories/{category}/documents/batch", files=[("files", (filename, text.encode(), "text/plain"))]
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["status"] == "stored"


def _process(client) -> dict:
    job = client.post("/process").json()
    body = client.get(f"/process/{job['job_id']}").json()
    assert body["status"] == "finished", body
    return body["result"]


def _indexed(store, **match) -> list[dict]:
    return [row for row in store._rows.values() if all(row[k] == v for k, v in match.items())]


def _long_text(topic: str, sentences: int) -> str:
    return " ".join(f"{topic} rule number {i} explains a distinct requirement in plain words." for i in range(sentences))


def test_a_deleted_file_is_removed_from_search_at_once_and_never_comes_back(client, _fake_vector_store):
    _upload(client, "Harassment", "discovery.txt", "Discovery of sexual conduct requires a noticed motion.")
    _upload(client, "Harassment", "evidence.txt", "Evidentiary issues include provocative conduct.")
    _process(client)
    assert _indexed(_fake_vector_store, filename="discovery.txt")

    response = client.delete("/categories/Harassment/documents/discovery.txt")

    assert response.status_code == 200
    assert _indexed(_fake_vector_store, filename="discovery.txt") == []  # immediately, before any re-index

    _process(client)  # the old pipeline re-indexed it from leftover files on disk

    assert _indexed(_fake_vector_store, filename="discovery.txt") == []
    assert _indexed(_fake_vector_store, filename="evidence.txt")


def test_a_replaced_file_keeps_no_chunks_from_its_old_version(client, _fake_vector_store):
    _upload(client, "Wage", "policy.txt", _long_text("Overtime", 80))
    _process(client)
    old_chunks = _indexed(_fake_vector_store, filename="policy.txt")
    assert len(old_chunks) > 1

    response = client.put(
        "/categories/Wage/documents/policy.txt",
        files={"file": ("policy.txt", b"Meal breaks are required after five hours of work.", "text/plain")},
    )

    assert response.status_code == 200
    assert _indexed(_fake_vector_store, filename="policy.txt") == []  # old text no longer citable

    _process(client)

    new_chunks = _indexed(_fake_vector_store, filename="policy.txt")
    assert len(new_chunks) == 1
    assert "Meal breaks" in new_chunks[0]["chunk_text"]
    assert not any("Overtime rule" in row["chunk_text"] for row in _fake_vector_store._rows.values())


def test_same_named_files_in_different_folders_are_indexed_separately(client, _fake_vector_store):
    _upload(client, "Harassment", "overview.txt", "Harassment overview: hostile work environment elements.")
    _upload(client, "Wage", "overview.txt", "Wage overview: minimum wage and overtime basics.")

    _process(client)

    rows = _indexed(_fake_vector_store, filename="overview.txt")
    assert {row["category"] for row in rows} == {"Harassment", "Wage"}
    assert len({row["document_id"] for row in rows}) == 2


def test_renaming_a_folder_relabels_its_chunks_without_leaving_duplicates(client, _fake_vector_store):
    _upload(client, "Employment_law", "termination.txt", "Wrongful termination requires a public policy violation.")
    _upload(client, "EmploymentXlaw", "other.txt", "Unrelated folder whose name differs only where _ would match.")
    _process(client)

    response = client.patch("/categories/Employment_law", json={"new_name": "Employment Law"})

    assert response.status_code == 200, response.text
    assert {row["category"] for row in _indexed(_fake_vector_store, filename="termination.txt")} == {"Employment Law"}
    assert _indexed(_fake_vector_store, filename="other.txt")[0]["category"] == "EmploymentXlaw"

    _process(client)

    rows = _indexed(_fake_vector_store, filename="termination.txt")
    assert len(rows) == 1 and rows[0]["category"] == "Employment Law"


def test_force_deleting_a_folder_removes_its_chunks_and_a_refused_delete_keeps_them(client, _fake_vector_store):
    _upload(client, "Old", "memo.txt", "An outdated memo that must stop being cited.")
    _upload(client, "Keep", "memo.txt", "A current memo.")
    _process(client)

    refused = client.delete("/categories/Old")
    assert refused.status_code == 409
    assert _indexed(_fake_vector_store, category="Old")

    response = client.delete("/categories/Old?force=true")

    assert response.status_code == 200
    assert _indexed(_fake_vector_store, category="Old") == []
    assert _indexed(_fake_vector_store, category="Keep")


def test_reindexing_never_touches_a_matters_own_documents(client, _fake_vector_store):
    _fake_vector_store.upsert_chunk_embedding(
        chunk_id="matter-7-upload-1-chunk-0000", document_id="matter-7-upload-1", category="matter-7",
        filename="client_statement.txt", chunk_text="The client's own statement.", embedding=[0.0] * 384,
        model_name="test", tenant_id=1,
    )
    _upload(client, "Harassment", "discovery.txt", "Discovery requires a noticed motion.")

    result = _process(client)

    assert _indexed(_fake_vector_store, category="matter-7")
    assert result["stale_chunks_removed"] == 0


def test_a_failed_search_index_update_stops_the_delete_with_nothing_changed(client, _fake_vector_store, monkeypatch):
    _upload(client, "Harassment", "discovery.txt", "Discovery requires a noticed motion.")

    def _unreachable(*args, **kwargs):
        raise ConnectionError("database down")

    monkeypatch.setattr(_fake_vector_store, "delete_document_chunks", _unreachable)

    response = client.delete("/categories/Harassment/documents/discovery.txt")

    assert response.status_code == 503
    assert [d["filename"] for d in client.get("/documents").json()["documents"]] == ["discovery.txt"]


def test_processing_refuses_to_clear_anything_if_one_folder_overlaps_the_original_uploads(tmp_path, monkeypatch):
    from app.embeddings import embedding_manager
    from app.extraction import extractor_manager
    from app.jobs.processing import _clear_derived_artifacts
    from app.segmentation import chunker, segmentation_manager

    originals = tmp_path / "storage" / "originals"
    (originals / "Docs").mkdir(parents=True)
    (originals / "Docs" / "keep.txt").write_text("irreplaceable")
    monkeypatch.setattr(extractor_manager, "ORIGINALS_DIR", originals)

    healthy = {}
    for module, attr in [
        (extractor_manager, "PROCESSED_DIR"), (segmentation_manager, "PROCESSED_DIR"),
        (segmentation_manager, "SEGMENTS_DIR"), (chunker, "SEGMENTS_DIR"),
        (embedding_manager, "CHUNKS_DIR"), (embedding_manager, "EMBEDDINGS_DIR"),
    ]:
        folder = tmp_path / "derived" / attr.lower()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sentinel.json").write_text("{}")
        healthy[folder] = True
        monkeypatch.setattr(module, attr, folder)
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "storage")  # misconfigured: a parent of originals

    with pytest.raises(RuntimeError, match="overlaps the original uploads"):
        _clear_derived_artifacts()

    assert (originals / "Docs" / "keep.txt").read_text() == "irreplaceable"
    # Nothing was cleared - not even the correctly configured folders.
    assert all((folder / "sentinel.json").exists() for folder in healthy)

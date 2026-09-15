"""
End-to-end tests for the admin storage API (app/api/storage_api.py),
covering the CRUD surface described in the module docstring plus the
newer subfolder and processing-status behavior.

Each test gets its own throwaway storage backend + metadata database
(via the `client` fixture) so nothing here touches real project
storage.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.storage.local_backend import LocalStorageBackend


@pytest.fixture
def client(tmp_path, monkeypatch):
    backend = LocalStorageBackend(
        originals_dir=tmp_path / "originals",
        quarantine_dir=tmp_path / "quarantine",
    )
    repository = SQLiteMetadataRepository(tmp_path / "metadata.db")

    monkeypatch.setattr(storage_api, "storage_backend", backend)
    monkeypatch.setattr(storage_api, "metadata_repository", repository)

    return TestClient(storage_api.app)


def _upload(client, category, filename, content=b"hello world"):
    return client.post(
        f"/categories/{category}/documents",
        files={"file": (filename, io.BytesIO(content), "text/plain")},
    )


# ---------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------


def test_create_and_list_category(client):
    response = client.post("/categories", json={"name": "Contracts"})
    assert response.status_code == 200
    assert response.json() == {"name": "Contracts", "document_count": 0}

    listed = client.get("/categories").json()["categories"]
    assert listed == [{"name": "Contracts", "document_count": 0}]


def test_create_subfolder_via_parent_field(client):
    client.post("/categories", json={"name": "Contracts"})
    response = client.post("/categories", json={"name": "2024", "parent": "Contracts"})

    assert response.json() == {"name": "Contracts/2024", "document_count": 0}

    names = {c["name"] for c in client.get("/categories").json()["categories"]}
    assert names == {"Contracts", "Contracts/2024"}


def test_upload_into_nested_category_path(client):
    response = _upload(client, "Contracts/2024", "agreement.txt")
    assert response.status_code == 200
    assert response.json()["category"] == "Contracts/2024"

    documents = client.get("/documents").json()["documents"]
    assert documents[0]["relative_path"] == "Contracts/2024/agreement.txt"


def test_rename_category_moves_documents(client):
    _upload(client, "Contracts", "a.txt")

    response = client.patch("/categories/Contracts", json={"new_name": "Agreements"})
    assert response.status_code == 200
    assert response.json()["name"] == "Agreements"

    documents = client.get("/documents").json()["documents"]
    assert documents[0]["category"] == "Agreements"


def test_rename_nested_category(client):
    _upload(client, "Contracts/2024", "a.txt")

    response = client.patch("/categories/Contracts/2024", json={"new_name": "Contracts/2025"})
    assert response.status_code == 200
    assert response.json()["name"] == "Contracts/2025"


def test_rename_missing_category_returns_404(client):
    response = client.patch("/categories/DoesNotExist", json={"new_name": "New"})
    assert response.status_code == 404


def test_delete_empty_category(client):
    client.post("/categories", json={"name": "Empty"})
    response = client.delete("/categories/Empty")
    assert response.status_code == 200
    assert client.get("/categories").json()["categories"] == []


def test_delete_nonempty_category_requires_force(client):
    _upload(client, "Full", "a.txt")

    response = client.delete("/categories/Full")
    assert response.status_code == 409

    response = client.delete("/categories/Full?force=true")
    assert response.status_code == 200
    assert client.get("/documents").json()["documents"] == []


def test_delete_missing_category_returns_404(client):
    response = client.delete("/categories/Nope")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------


def test_upload_rejects_invalid_extension(client):
    response = _upload(client, "Docs", "malware.exe")
    body = response.json()
    assert body["results"][0]["status"] == "rejected"
    assert body["total_stored"] == 0


def test_batch_upload_openapi_schema_renders_file_picker_in_swagger(client):
    """
    Regression test for the Swagger UI multi-file picker fix: the
    `files` array's items must carry `format: binary` (in addition to
    OpenAPI 3.1's `contentMediaType`), which is the keyword Swagger
    UI's array-of-files widget actually checks for.
    """

    schema = client.get("/openapi.json").json()
    batch_schema = schema["components"]["schemas"][
        "Body_upload_documents_batch_categories__category__documents_batch_post"
    ]

    files_items = batch_schema["properties"]["files"]["items"]
    assert files_items["format"] == "binary"
    assert files_items["contentMediaType"] == "application/octet-stream"


def test_upload_batch(client):
    response = client.post(
        "/categories/Docs/documents/batch",
        files=[
            ("files", ("a.txt", io.BytesIO(b"one"), "text/plain")),
            ("files", ("b.txt", io.BytesIO(b"two"), "text/plain")),
        ],
    )
    body = response.json()
    assert body["total_stored"] == 2


def test_replace_document_keeps_filename_updates_contents(client):
    _upload(client, "Docs", "report.txt", content=b"old")

    response = client.put(
        "/categories/Docs/documents/report.txt",
        files={"file": ("report.txt", io.BytesIO(b"new content"), "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["size"] == len(b"new content")

    documents = client.get("/documents").json()["documents"]
    assert documents[0]["status"] == "Uploaded"


def test_replace_missing_document_returns_404(client):
    response = client.put(
        "/categories/Docs/documents/missing.txt",
        files={"file": ("missing.txt", io.BytesIO(b"data"), "text/plain")},
    )
    assert response.status_code == 404


def test_delete_document(client):
    _upload(client, "Docs", "report.txt")

    response = client.delete("/categories/Docs/documents/report.txt")
    assert response.status_code == 200
    assert client.get("/documents").json()["documents"] == []


def test_delete_document_does_not_shadow_delete_category(client):
    """
    Regression test: DELETE /categories/{category}/documents/{filename}
    must route to delete_document, not fall through to the greedy
    DELETE /categories/{category} route.
    """

    _upload(client, "Contracts/2024", "report.txt")

    response = client.delete("/categories/Contracts/2024/documents/report.txt")
    assert response.status_code == 200
    assert "deleted from" in response.json()["message"]

    # The category itself must still exist - only the document was removed.
    names = {c["name"] for c in client.get("/categories").json()["categories"]}
    assert "Contracts/2024" in names


def test_delete_missing_document_returns_404(client):
    response = client.delete("/categories/Docs/documents/missing.txt")
    assert response.status_code == 404


def test_list_documents_filters_by_category(client):
    _upload(client, "Contracts", "a.txt")
    _upload(client, "Other", "b.txt")

    documents = client.get("/documents?category=Contracts").json()["documents"]
    assert len(documents) == 1
    assert documents[0]["category"] == "Contracts"


# ---------------------------------------------------------------------
# Processing status
# ---------------------------------------------------------------------


def test_process_transitions_document_status_to_indexed(client, tmp_path, monkeypatch):
    from app.embeddings import embedding_manager
    from app.extraction import extractor_manager
    from app.segmentation import chunker, segmentation_manager

    monkeypatch.setattr(extractor_manager, "ORIGINALS_DIR", tmp_path / "originals")
    monkeypatch.setattr(extractor_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(embedding_manager, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(embedding_manager, "EMBEDDINGS_DIR", tmp_path / "embeddings")

    _upload(client, "Docs", "report.txt", content=b"Some real content to process.")

    documents = client.get("/documents").json()["documents"]
    assert documents[0]["status"] == "Uploaded"

    response = client.post("/process")
    assert response.status_code == 200
    queued = response.json()
    assert queued["status"] == "queued"
    assert queued["job_id"]

    # The fake queue (see conftest.py's _fake_job_queue) runs the job
    # synchronously, so it has already finished by the time we poll -
    # a real worker would take longer, which is the point: POST
    # /process returned immediately either way.
    status_response = client.get(f"/process/{queued['job_id']}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "finished"
    assert body["result"]["documents_extracted"] == 1
    assert body["result"]["segments_created"] == 1
    assert body["result"]["chunks_created"] == 1
    assert body["result"]["embeddings_created"] == 1

    documents = client.get("/documents").json()["documents"]
    assert documents[0]["status"] == "Indexed"


def test_process_marks_extraction_failure(client, tmp_path, monkeypatch):
    from app.embeddings import embedding_manager
    from app.extraction import extractor_manager
    from app.segmentation import chunker, segmentation_manager

    monkeypatch.setattr(extractor_manager, "ORIGINALS_DIR", tmp_path / "originals")
    monkeypatch.setattr(extractor_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(embedding_manager, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(embedding_manager, "EMBEDDINGS_DIR", tmp_path / "embeddings")

    # A .pdf extension containing non-PDF bytes fails extraction.
    client.post("/categories", json={"name": "Docs"})
    (tmp_path / "originals" / "Docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "originals" / "Docs" / "broken.pdf").write_text("not a pdf", encoding="utf-8")
    storage_api.metadata_repository.upsert_document("Docs", "broken.pdf", ".pdf", 9, "x")

    response = client.post("/process")
    assert response.status_code == 200
    queued = response.json()

    status_response = client.get(f"/process/{queued['job_id']}")
    assert status_response.json()["result"]["documents_extraction_failed"] == 1

    documents = client.get("/documents").json()["documents"]
    assert documents[0]["status"] == "Failed"


# ---------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------


def test_search_returns_reranked_chunks(client, monkeypatch):
    """
    Exercises POST /search's wiring end to end (request schema ->
    app/retrieval/retriever.retrieve() -> response schema) without a
    real pgvector database - similarity_search()/keyword_search()
    themselves are covered against real Postgres in
    tests/test_vector_store.py, and the fusion logic on its own in
    tests/test_retrieval.py.
    """

    from app.retrieval import search as retrieval_search

    def fake_vector_search(query, top_k, category=None):
        return [
            {
                "chunk_id": "c-1",
                "document_id": "policy",
                "category": "Docs",
                "filename": "policy.txt",
                "chunk_text": "The vendor risk policy requires annual review.",
                "metadata": {},
                "score": 0.9,
            }
        ]

    def fake_keyword_search(query, top_k, category=None):
        return []

    monkeypatch.setattr(retrieval_search, "vector_search", fake_vector_search)
    monkeypatch.setattr(retrieval_search, "keyword_search", fake_keyword_search)
    monkeypatch.setattr(
        "app.retrieval.retriever.vector_search", fake_vector_search
    )
    monkeypatch.setattr(
        "app.retrieval.retriever.keyword_search", fake_keyword_search
    )

    response = client.post("/search", json={"query": "vendor risk policy", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "vendor risk policy"
    assert len(body["results"]) == 1
    assert body["results"][0]["chunk_id"] == "c-1"
    assert body["results"][0]["final_score"] > 0


def test_search_rejects_empty_query(client):
    response = client.post("/search", json={"query": ""})
    assert response.status_code == 422

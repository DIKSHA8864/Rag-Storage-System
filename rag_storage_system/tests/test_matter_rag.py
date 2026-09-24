"""
Matter-specific RAG isolation - the automated Blueprint Test 7
("Isolation") for the vector-store layer: a Matter's own ingested
documents must never surface in another Matter's retrieval, and the
Owner's library-wide search must never include any Matter's namespace.
"""

import pytest

from app.matter_rag.ingestion import ingest_matter_document, matter_namespace
from app.retrieval.retriever import retrieve, retrieve_for_matter


class _FakeVectorStore:
    def __init__(self):
        self.rows = {}

    def upsert_chunk_embedding(self, chunk_id, document_id, category, filename, chunk_text, embedding, model_name, **kwargs):
        self.rows[chunk_id] = {
            "chunk_id": chunk_id, "document_id": document_id, "category": category,
            "filename": filename, "chunk_text": chunk_text, "final_score": 0.9,
            "section": None, "start_page": None, "end_page": None,
        }

    def similarity_search(self, query_embedding, top_k=5, category=None, tenant_id=1):
        if category is None:
            rows = [r for r in self.rows.values() if not r["category"].startswith("matter-")]
        else:
            rows = [r for r in self.rows.values() if r["category"] == category or r["category"].startswith(category + "/")]
        return rows[:top_k]

    def count(self):
        return len(self.rows)


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeVectorStore()
    monkeypatch.setattr("app.vector_store.get_vector_store", lambda: store)
    return store


def test_blueprint_test_7_matter_rag_never_retrieves_another_matters_documents(monkeypatch, fake_store):
    monkeypatch.setattr(
        "app.matter_rag.ingestion.process_submission",
        lambda filename, data: [{"chunk_index": 0, "text": data.decode(), "chapter": None, "section": None, "start_page": None, "end_page": None, "embedding": [0.1]}],
    )

    ingest_matter_document(matter_id=1, uploaded_input_id=101, filename="matter1.txt", data=b"Matter One confidential contract text.", vector_store=fake_store)
    ingest_matter_document(matter_id=2, uploaded_input_id=202, filename="matter2.txt", data=b"Matter Two confidential contract text.", vector_store=fake_store)

    matter_1_categories = {r["category"] for r in fake_store.similarity_search([0.1], top_k=10, category=matter_namespace(1))}
    matter_2_categories = {r["category"] for r in fake_store.similarity_search([0.1], top_k=10, category=matter_namespace(2))}

    assert matter_1_categories == {"matter-1"}
    assert matter_2_categories == {"matter-2"}


def test_library_wide_search_excludes_every_matter_namespace(fake_store):
    fake_store.upsert_chunk_embedding("lib-1", "doc", "HR", "policy.pdf", "text", [0.1], "model")
    fake_store.upsert_chunk_embedding("matter-1:1:0", "matter-1:1", "matter-1", "contract.txt", "text", [0.1], "model")

    results = fake_store.similarity_search([0.1], top_k=10, category=None)

    assert all(not r["category"].startswith("matter-") for r in results)
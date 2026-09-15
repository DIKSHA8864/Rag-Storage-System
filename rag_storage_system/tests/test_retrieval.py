"""
Tests for app/retrieval/: the reranker's score fusion (pure Python, no
external dependency) and the retriever's orchestration (mocked search
functions - vector_search()/keyword_search() themselves are exercised
against a real pgvector database in tests/test_vector_store.py).
"""

from app.retrieval.reranker import rerank
from app.retrieval.retriever import retrieve


def _hit(chunk_id: str, score: float, text: str = "some text") -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": "doc",
        "category": "Docs",
        "filename": "doc.txt",
        "chunk_text": text,
        "metadata": {},
        "score": score,
    }


# ---------------------------------------------------------------------
# reranker.rerank()
# ---------------------------------------------------------------------


def test_rerank_ranks_chunk_found_by_both_signals_first():
    # "b" isn't the top vector hit on its own, but keyword search
    # corroborating it should be enough to overtake "a" - the reason
    # hybrid search combines both instead of using vector search alone.
    vector_hits = [_hit("a", 0.9), _hit("b", 0.85), _hit("c", 0.3)]
    keyword_hits = [_hit("b", 10.0)]

    ranked = rerank(vector_hits, keyword_hits, top_k=5)

    assert ranked[0]["chunk_id"] == "b"
    assert ranked[0]["vector_score"] > 0
    assert ranked[0]["keyword_score"] > 0


def test_rerank_respects_top_k():
    # Scores in a realistic cosine-similarity range (0-1) - rerank()
    # clamps rather than rescales, so a range beyond that would just
    # collapse to ties instead of testing ordering.
    vector_hits = [_hit(f"c{i}", score=i / 10) for i in range(10)]

    ranked = rerank(vector_hits, [], top_k=3)

    assert len(ranked) == 3
    # Highest raw vector score should come first.
    assert ranked[0]["chunk_id"] == "c9"


def test_rerank_handles_no_hits():
    assert rerank([], [], top_k=5) == []


def test_rerank_chunk_only_in_keyword_hits_still_included():
    ranked = rerank([], [_hit("only-keyword", 1.0)], top_k=5)

    assert len(ranked) == 1
    assert ranked[0]["chunk_id"] == "only-keyword"
    assert ranked[0]["vector_score"] == 0.0


# ---------------------------------------------------------------------
# retriever.retrieve()
# ---------------------------------------------------------------------


def test_retrieve_calls_vector_and_keyword_search_with_wider_candidate_pool(monkeypatch):
    calls = {}

    def fake_vector_search(query, top_k, category=None):
        calls["vector"] = (query, top_k, category)
        return [_hit("v1", 0.8)]

    def fake_keyword_search(query, top_k, category=None):
        calls["keyword"] = (query, top_k, category)
        return [_hit("k1", 5.0)]

    monkeypatch.setattr("app.retrieval.retriever.vector_search", fake_vector_search)
    monkeypatch.setattr("app.retrieval.retriever.keyword_search", fake_keyword_search)

    results = retrieve("what is the policy?", top_k=2, category="Docs")

    assert calls["vector"] == ("what is the policy?", 8, "Docs")
    assert calls["keyword"] == ("what is the policy?", 8, "Docs")
    assert {r["chunk_id"] for r in results} == {"v1", "k1"}


def test_retrieve_returns_at_most_top_k(monkeypatch):
    monkeypatch.setattr(
        "app.retrieval.retriever.vector_search",
        lambda query, top_k, category=None: [_hit(f"v{i}", float(i)) for i in range(20)],
    )
    monkeypatch.setattr(
        "app.retrieval.retriever.keyword_search", lambda query, top_k, category=None: []
    )

    results = retrieve("query", top_k=3)

    assert len(results) == 3

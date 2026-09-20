"""
PHASE 7 - RETRIEVAL

The full hybrid retrieval pipeline:

    query -> query embedding
          -> vector search + keyword search + metadata filtering (run together)
          -> reranking
          -> top relevant chunks

Plain vector similarity alone misses exact keyword/number/proper-noun
matches and can't be filtered/verified against anything else, so
vector search and keyword search run side by side (app/retrieval/
search.py) - not one instead of the other - and get fused by
app/retrieval/reranker.py. "Metadata filtering" is the `category`
argument both searches already take, narrowing the candidate set
before ranking rather than after.
"""

from typing import Optional

from app.retrieval.reranker import rerank
from app.retrieval.search import keyword_search, vector_search

# Retrieve more candidates than requested from each signal before
# reranking - a chunk ranked #8 by vector search but #1 by keyword
# search would be lost if only the top few from each were considered.
_CANDIDATE_MULTIPLIER = 4


def retrieve(
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
    score_threshold: float = 0.0,
) -> list[dict]:
    """
    Run the full hybrid retrieval pipeline for `query` and return its
    top_k most relevant chunks (highest final_score first), dropping
    any chunk whose final_score is below `score_threshold` (default
    0.0 keeps every existing caller's behavior unchanged - see
    app/retrieval_settings.py for where a non-zero threshold comes
    from).

    Each result includes chunk_id, document_id, category, filename,
    chunk_text, metadata, vector_score, keyword_score, and
    final_score - enough to inspect *why* a chunk ranked where it did,
    which matters for judging retrieval quality (see
    tests/test_retrieval.py and scripts/test_retrieval.py).
    """

    candidate_count = top_k * _CANDIDATE_MULTIPLIER

    vector_hits = vector_search(query, top_k=candidate_count, category=category)
    keyword_hits = keyword_search(query, top_k=candidate_count, category=category)

    ranked = rerank(vector_hits, keyword_hits, top_k=top_k)

    return [chunk for chunk in ranked if chunk["final_score"] >= score_threshold]

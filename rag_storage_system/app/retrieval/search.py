"""
The two independent retrieval signals app/retrieval/retriever.py runs
side by side and then merges: vector similarity and keyword match.
Both query app/vector_store's chunk_embeddings table (via
get_vector_store()), just through different methods of it - see
app/vector_store/vector_repository.py.
"""

from typing import Optional

from app.embeddings.embedding_manager import embed_texts
from app.vector_store import get_vector_store


def vector_search(query: str, top_k: int = 10, category: Optional[str] = None) -> list[dict]:
    """Embed `query` and return the top_k chunks nearest it by cosine similarity."""

    query_embedding = embed_texts([query])[0]

    return get_vector_store().similarity_search(
        query_embedding, top_k=top_k, category=category
    )


def keyword_search(query: str, top_k: int = 10, category: Optional[str] = None) -> list[dict]:
    """
    Return the top_k chunks whose text best matches `query` by plain
    keyword search (Postgres full-text search - see
    PgVectorRepository.keyword_search()).

    Catches queries vector search alone tends to miss - an exact
    product code, a proper noun, a number - where a chunk's wording
    literally matches the query but isn't necessarily its closest
    embedding neighbor.
    """

    vector_store = get_vector_store()

    if not hasattr(vector_store, "keyword_search"):
        return []

    return vector_store.keyword_search(query, top_k=top_k, category=category)

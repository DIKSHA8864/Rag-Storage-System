"""
Vector store interface.

Same abstraction principle as app/storage/base.py and
app/metadata/base.py: everything that stores/searches chunk embedding
vectors goes through an object that implements VectorStore, instead of
a caller (the background job, app/retrieval/) talking to psycopg or a
vector-DB SDK directly. Today that resolves to PgVectorRepository
(app/vector_store/vector_repository.py), using the pgvector extension
on the same Postgres already running for metadata - no new database
needed. Swapping in Chroma or a hosted vector DB later is a factory
change in app/vector_store/__init__.py, not a rewrite of the job or
the retrieval pipeline.
"""

from abc import ABC, abstractmethod
from typing import Optional


class VectorStore(ABC):
    """Abstract base class for all vector store backends."""

    @abstractmethod
    def upsert_chunk_embedding(
        self,
        chunk_id: str,
        document_id: str,
        category: str,
        filename: str,
        chunk_text: str,
        embedding: list[float],
        model_name: str,
        metadata: Optional[dict] = None,
        chapter: Optional[str] = None,
        section: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
        tenant_id: int = 1,
    ) -> None:
        """
        Insert one chunk's embedding, or replace it in place if
        chunk_id already exists.

        chapter/section/start_page/end_page are the chunk's location
        within its source document (already computed by
        app/segmentation/chunker.py) - stored so a caller can cite
        exact evidence (file name, page, section) later, not just the
        chunk's raw text (see app/analysis/).

        `tenant_id` is the actual cross-tenant RAG-leak boundary - see
        similarity_search() below.
        """
        raise NotImplementedError

    @abstractmethod
    def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        category: Optional[str] = None,
        tenant_id: int = 1,
    ) -> list[dict]:
        """
        Return the `top_k` chunks whose embedding is nearest
        `query_embedding` (nearest first), always restricted to
        `tenant_id` and optionally further narrowed to one category.

        tenant_id filtering is unconditional (never optional/None) -
        this is what stops one firm's confidential documents from ever
        surfacing in another firm's research answer.

        Each result is a dict with at least:
            chunk_id, document_id, category, filename, chunk_text,
            chapter, section, start_page, end_page, metadata, score
            (higher is more similar, in [0, 1] for cosine similarity)
        """
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        """Total number of chunk embeddings currently stored."""
        raise NotImplementedError

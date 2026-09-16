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
    ) -> None:
        """
        Insert one chunk's embedding, or replace it in place if
        chunk_id already exists.

        chapter/section/start_page/end_page are the chunk's location
        within its source document (already computed by
        app/segmentation/chunker.py) - stored so a caller can cite
        exact evidence (file name, page, section) later, not just the
        chunk's raw text (see app/analysis/).
        """
        raise NotImplementedError

    @abstractmethod
    def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        Return the `top_k` chunks whose embedding is nearest
        `query_embedding` (nearest first), optionally restricted to
        one category.

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

    @abstractmethod
    def delete_by_document(self, category: str, filename: str) -> int:
        """
        Delete every chunk embedding belonging to one document.
        Returns how many rows were removed.

        Matched on (category, filename) rather than document_id:
        document_id is only the filename stem (see
        app/jobs/processing.py), so two files named report.pdf in
        different categories share one - and deleting either must
        never take the other's vectors with it.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_by_category(self, category: str) -> int:
        """
        Delete every chunk embedding in a category and its
        subcategories, mirroring similarity_search()'s subfolder
        matching. Returns how many rows were removed.
        """
        raise NotImplementedError

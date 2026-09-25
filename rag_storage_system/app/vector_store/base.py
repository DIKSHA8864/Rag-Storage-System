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

    # ------------------------------------------------------------------
    # Keeping the library index in step with the library itself. Every
    # method below touches library chunks only - never a Matter's own
    # namespace (category "matter-<id>", see app/matter_rag/) - and is
    # always scoped to one tenant unless it says otherwise.
    # ------------------------------------------------------------------

    @abstractmethod
    def delete_document_chunks(self, category: str, filename: str, tenant_id: int) -> int:
        """Remove every chunk of one library file (deleted or replaced). Returns how many were removed."""
        raise NotImplementedError

    @abstractmethod
    def delete_category_chunks(self, category: str, tenant_id: int) -> int:
        """Remove every chunk under a library folder and its subfolders. Returns how many were removed."""
        raise NotImplementedError

    @abstractmethod
    def rename_category_chunks(self, old_category: str, new_category: str, tenant_id: int) -> int:
        """Re-label chunks after a folder rename/move (subfolders follow). Returns how many were updated."""
        raise NotImplementedError

    @abstractmethod
    def delete_library_chunks_except(self, keep_chunk_ids: set[str]) -> int:
        """
        Remove every library chunk (all tenants) NOT in `keep_chunk_ids` -
        run by app/jobs/processing.py after a full re-index, whose chunk
        set is the complete, current library. Clears what a deleted file,
        a shrunken re-upload, or a renamed/moved file left behind.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_matter_document_chunks(self, matter_id: int, document_id: str, tenant_id: int) -> int:
        """Remove one document's chunks from a Matter's own namespace ("matter-<id>") - never library chunks."""
        raise NotImplementedError

    @abstractmethod
    def chunk_sources(self, chunk_ids: list[str], tenant_id: int) -> dict[str, dict]:
        """chunk_id -> {"filename", "category"} for those of `chunk_ids` that still exist in `tenant_id`'s index."""
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        """Total number of chunk embeddings currently stored."""
        raise NotImplementedError

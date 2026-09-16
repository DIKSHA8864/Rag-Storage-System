"""
The background job POST /process enqueues (see app/jobs/queue.py and
scripts/worker.py).

This is the exact extraction -> segmentation -> chunking -> embeddings
pipeline that used to run inline inside the POST /process request
handler (app/api/storage_api.py), plus one more step: each chunk's
embedding is now also written to pgvector (app/vector_store/) so
app/retrieval/ has something to search. Moving all of it here means it
runs in a separate worker process instead of the request/response
cycle, so a slow document being processed doesn't block the API from
answering other requests (new uploads, status polls, etc).
"""

from pathlib import Path
from typing import Optional

from app.embeddings.embedding_manager import process_all_chunks
from app.extraction.extractor_manager import extract_all_documents
from app.metadata import get_metadata_repository
from app.metadata.base import MetadataRepository
from app.metadata.models import DocumentStatus
from app.segmentation.chunker import process_all_segments
from app.segmentation.segmentation_manager import process_all_documents
from app.storage.base import StorageBackend
from app.vector_store import get_vector_store
from app.vector_store.base import VectorStore


def run_processing_job(
    metadata_repository: Optional[MetadataRepository] = None,
    vector_store: Optional[VectorStore] = None,
    storage_backend: Optional[StorageBackend] = None,
) -> dict:
    """
    Run every stored document through extraction, segmentation,
    chunking, embedding generation, and pgvector indexing, updating
    each document's status in Postgres/SQLite along the way:
    Uploaded -> Processing -> Embedding -> Indexed, or -> Failed on an
    extraction error.

    `metadata_repository` and `vector_store` are passed in by the
    caller (POST /process passes its own instances so the worker
    updates the exact same databases, rather than each side
    independently resolving METADATA_BACKEND/postgres_dsn) and default
    to the standard factories for any other caller (e.g. running this
    module directly).

    Safe to run again after new uploads - it always reprocesses
    everything currently in storage. Returns the same summary counts
    POST /process used to return directly before processing became
    asynchronous; fetch it via GET /process/{job_id} once the job
    finishes.
    """

    metadata_repository = metadata_repository or get_metadata_repository()
    vector_store = vector_store or get_vector_store()

    # Left as None by POST /process: a live S3 client can't be
    # pickled onto the RQ queue, so the worker resolves the
    # backend from its own config instead of receiving one.
    extraction_results = extract_all_documents(storage_backend)

    documents_extracted = sum(
        1 for result in extraction_results if result["status"] == "extracted"
    )
    documents_failed = sum(
        1 for result in extraction_results if result["status"] == "failed"
    )

    # Chunks/embeddings only carry a document_id (the filename stem -
    # see app/segmentation/segmentation_manager.py), not the category
    # it came from, so it's recovered here from this same extraction
    # pass rather than threading a new field through every phase.
    category_by_document_id: dict[str, str] = {}

    for result in extraction_results:
        if result["status"] == "extracted":
            metadata_repository.update_document_status(
                result["category"], result["filename"], DocumentStatus.PROCESSING.value
            )
            category_by_document_id[Path(result["filename"]).stem] = result["category"]
        else:
            metadata_repository.update_document_status(
                result["category"],
                result["filename"],
                DocumentStatus.FAILED.value,
                status_detail=result["error"],
            )

    segments = process_all_documents()
    chunks = process_all_segments()
    embeddings = process_all_chunks()

    metadata_repository.update_status_where(
        DocumentStatus.PROCESSING.value, DocumentStatus.EMBEDDING.value
    )

    for embedding in embeddings:
        vector_store.upsert_chunk_embedding(
            chunk_id=embedding["chunk_id"],
            document_id=embedding["document_id"],
            category=category_by_document_id.get(embedding["document_id"], "uncategorized"),
            filename=embedding["filename"],
            chunk_text=embedding["text"],
            embedding=embedding["embedding"],
            model_name=embedding["embedding_model"],
            metadata=embedding.get("metadata", {}),
            chapter=embedding.get("chapter"),
            section=embedding.get("section"),
            start_page=embedding.get("start_page"),
            end_page=embedding.get("end_page"),
        )

    metadata_repository.update_status_where(
        DocumentStatus.EMBEDDING.value, DocumentStatus.INDEXED.value
    )

    return {
        "documents_extracted": documents_extracted,
        "documents_extraction_failed": documents_failed,
        "segments_created": len(segments),
        "chunks_created": len(chunks),
        "embeddings_created": len(embeddings),
    }

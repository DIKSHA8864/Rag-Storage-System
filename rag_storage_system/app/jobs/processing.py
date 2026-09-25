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

import logging
import shutil
from pathlib import Path
from typing import Optional

from app.embeddings import embedding_manager
from app.embeddings.embedding_manager import process_all_chunks
from app.extraction import extractor_manager
from app.extraction.extractor_manager import extract_all_documents
from app.metadata import get_metadata_repository
from app.metadata.base import MetadataRepository
from app.metadata.models import DocumentStatus
from app.segmentation import chunker, segmentation_manager
from app.segmentation.chunker import process_all_segments
from app.segmentation.segmentation_manager import process_all_documents
from app.vector_store import get_vector_store
from app.vector_store.base import VectorStore


logger = logging.getLogger(__name__)


def _derived_artifact_dirs() -> set[Path]:
    """Every intermediate folder a run writes and a later phase reads back (read at call time - tests repoint them)."""

    return {
        Path(extractor_manager.PROCESSED_DIR).resolve(),
        Path(segmentation_manager.PROCESSED_DIR).resolve(),
        Path(segmentation_manager.SEGMENTS_DIR).resolve(),
        Path(chunker.SEGMENTS_DIR).resolve(),
        Path(chunker.CHUNKS_DIR).resolve(),
        Path(embedding_manager.CHUNKS_DIR).resolve(),
        Path(embedding_manager.EMBEDDINGS_DIR).resolve(),
    }


def _clear_derived_artifacts() -> None:
    """
    Each phase rebuilds its output from everything on disk, so leftover
    extracted/segment/chunk files of a deleted, replaced, or moved file
    would be re-indexed on every run. They are all rebuilt from the
    originals below anyway - clear them first. Refuses (raises) rather
    than ever clearing a folder that holds, or is, the uploaded originals.
    """

    originals = Path(extractor_manager.ORIGINALS_DIR).resolve()
    directories = _derived_artifact_dirs()

    # Every folder is checked before ANY is cleared - one bad setting
    # must stop the whole clear, not be discovered halfway through it.
    for directory in directories:
        if directory == originals or directory in originals.parents or originals in directory.parents:
            raise RuntimeError(
                f"Refusing to clear '{directory}': it overlaps the original uploads folder '{originals}'. "
                "Check the *_STORAGE_PATH settings."
            )

    for directory in directories:
        if directory.exists():
            for child in directory.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()


def run_processing_job(
    metadata_repository: Optional[MetadataRepository] = None,
    vector_store: Optional[VectorStore] = None,
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

    _clear_derived_artifacts()
    extraction_results = extract_all_documents()

    documents_extracted = sum(
        1 for result in extraction_results if result["status"] == "extracted"
    )
    documents_failed = sum(
        1 for result in extraction_results if result["status"] == "failed"
    )

    # Chunks/embeddings only carry a document_id, not the category or
    # tenant they came from, so both are recovered here from this same
    # extraction pass. document_id is unique per storage path
    # (extractor_manager.library_document_id()), so two same-named files
    # in different folders or organizations never share - or overwrite -
    # each other's chunks.
    category_by_document_id: dict[str, str] = {}
    tenant_id_by_document_id: dict[str, int] = {}

    for result in extraction_results:
        tenant_id = result.get("tenant_id", 1)
        if result["status"] == "extracted":
            ocr_pages_used = result.get("ocr_pages_used", 0)
            status_detail = (
                f"{ocr_pages_used} page(s) had no extractable text layer and were read via "
                "OCR fallback instead - configure OCR_PROVIDER for real text extraction if this "
                "is still the mock provider."
                if ocr_pages_used
                else None
            )
            metadata_repository.update_document_status(
                result["category"], result["filename"], DocumentStatus.PROCESSING.value,
                status_detail=status_detail, tenant_id=tenant_id,
            )
            category_by_document_id[result["document_id"]] = result["category"]
            tenant_id_by_document_id[result["document_id"]] = tenant_id
        else:
            metadata_repository.update_document_status(
                result["category"],
                result["filename"],
                DocumentStatus.FAILED.value,
                status_detail=result["error"],
                tenant_id=tenant_id,
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
            tenant_id=tenant_id_by_document_id.get(embedding["document_id"], 1),
        )

    # This run's chunks are the whole current library - anything else
    # in the index belongs to a file that was deleted, replaced with
    # fewer chunks, moved, renamed, or failed to extract this time.
    # Removed only now, after the new chunks are in, so search never
    # has a window with the library missing.
    stale_chunks_removed = vector_store.delete_library_chunks_except(
        {embedding["chunk_id"] for embedding in embeddings}
    )
    if stale_chunks_removed:
        logger.info("Removed %d stale chunk(s) from the library index.", stale_chunks_removed)

    metadata_repository.update_status_where(
        DocumentStatus.EMBEDDING.value, DocumentStatus.INDEXED.value
    )

    return {
        "documents_extracted": documents_extracted,
        "documents_extraction_failed": documents_failed,
        "segments_created": len(segments),
        "chunks_created": len(chunks),
        "embeddings_created": len(embeddings),
        "stale_chunks_removed": stale_chunks_removed,
    }

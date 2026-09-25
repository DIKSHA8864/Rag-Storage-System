"""
Background indexing of an attorney's case document (pleading, order,
correspondence...) into its matter's own namespace ("matter-<id>" -
app/matter_rag/). It is then searchable only by that matter's research,
reports and complaint drafts, never by the library or another matter.
"""

import logging

logger = logging.getLogger(__name__)


def case_document_id(document_id: int) -> str:
    return f"case-{document_id}"


def case_document_chunk_group(matter_id: int, document_id: int) -> str:
    """The vector-store document_id every chunk of this case document carries (see ingest_matter_document)."""

    from app.matter_rag.ingestion import matter_namespace

    return f"{matter_namespace(matter_id)}:{case_document_id(document_id)}"


def run_matter_document_job(document_id: int, matter_id: int, metadata_repository, storage_backend, vector_store) -> dict:
    from app.matter_rag.ingestion import ingest_matter_document

    document = metadata_repository.get_matter_document(document_id, matter_id)
    if document is None:
        return {"status": "gone"}

    try:
        with storage_backend.open_file(document["stored_category"], document["stored_filename"]) as f:
            data = f.read()
        # Re-indexing starts clean, so a shorter new version leaves no stale chunks behind.
        vector_store.delete_matter_document_chunks(matter_id, case_document_chunk_group(matter_id, document_id), document["tenant_id"])
        chunk_count = ingest_matter_document(
            matter_id, case_document_id(document_id), document["original_filename"], data,
            vector_store=vector_store, tenant_id=document["tenant_id"],
        )
    except Exception as exc:
        logger.exception("Indexing case document %s failed", document_id)
        metadata_repository.update_matter_document_status(document_id, "failed", 0, f"Indexing failed: {exc}"[:500])
        return {"status": "failed"}

    if chunk_count == 0:
        metadata_repository.update_matter_document_status(
            document_id, "failed", 0, "No text could be read from this file (a scanned PDF without OCR text?)."
        )
        return {"status": "failed"}

    metadata_repository.update_matter_document_status(document_id, "indexed", chunk_count)
    return {"status": "indexed", "chunks": chunk_count}

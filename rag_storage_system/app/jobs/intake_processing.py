"""
Background job POST /end-user/intake/sessions/{id}/uploads enqueues
(app/jobs/queue.py, mirroring app/jobs/processing.py's
run_processing_job) - runs one uploaded_input through
app/multimodal/pipeline.py and records the result.
"""

from typing import Optional

from app.metadata import get_metadata_repository
from app.metadata.base import MetadataRepository
from app.multimodal.pipeline import process_uploaded_input
from app.storage import get_intake_storage_backend
from app.storage.base import StorageBackend


def run_intake_processing_job(
    uploaded_input_id: int,
    metadata_repository: Optional[MetadataRepository] = None,
    storage_backend: Optional[StorageBackend] = None,
) -> dict:
    """
    Load the stored file for `uploaded_input_id`, run it through the
    multimodal pipeline, persist every extracted_information row, and
    update uploaded_inputs.processing_status accordingly
    (queued -> processing -> completed/failed/partial). Always appends
    a timeline_event, whatever the outcome, so an intake session's
    history is complete even for a failure.
    """

    metadata_repository = metadata_repository or get_metadata_repository()
    storage_backend = storage_backend or get_intake_storage_backend()

    uploaded_input = metadata_repository.get_uploaded_input(uploaded_input_id)
    if uploaded_input is None:
        raise ValueError(f"No such uploaded_input: {uploaded_input_id}")

    metadata_repository.update_uploaded_input_status(uploaded_input_id, "processing")

    with storage_backend.open_file(uploaded_input["stored_category"], uploaded_input["stored_filename"]) as f:
        data = f.read()

   result = process_uploaded_input(uploaded_input["original_filename"], data)

    for item in result.extracted:
        metadata_repository.add_extracted_information(
            uploaded_input_id=uploaded_input_id,
            content_type=item.content_type,
            text=item.text,
            provider=item.provider,
            is_mock=item.is_mock,
            archive_member_filename=item.archive_member_filename,
        )

    metadata_repository.update_uploaded_input_status(
        uploaded_input_id, result.status.value, status_detail=result.status_detail
    )

    if uploaded_input.get("matter_id") is not None and result.status.value in ("completed", "partial"):
        from app.matter_rag.ingestion import ingest_matter_document

        try:
            ingest_matter_document(uploaded_input["matter_id"], uploaded_input_id, uploaded_input["original_filename"], data)
        except Exception:
            # Matter-namespace RAG ingestion is best-effort - a client's
            # document still gets extracted/reported even if this
            # (network-dependent embedding) step is unavailable, same
            # resilience philosophy as app/report/rag_analysis.py's
            # retrieval-failure handling.
            metadata_repository.add_timeline_event(
                uploaded_input["intake_session_id"], "matter_rag_ingestion_failed",
                f"Could not index '{uploaded_input['original_filename']}' into the Matter's own RAG namespace.",
            )
    metadata_repository.add_timeline_event(
        uploaded_input["intake_session_id"],
        "input_processed",
        f"'{uploaded_input['original_filename']}' processing finished: {result.status.value}"
        + (f" ({result.status_detail})" if result.status_detail else ""),
    )

    return {
        "uploaded_input_id": uploaded_input_id,
        "status": result.status.value,
        "extracted_count": len(result.extracted),
    }

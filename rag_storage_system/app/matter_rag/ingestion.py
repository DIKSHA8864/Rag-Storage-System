"""
Ingests one Matter document into that Matter's own retrieval namespace
(category f"matter-{matter_id}") - reusing app/analysis/ingestion.py's
process_submission() (the exact extract -> segment -> chunk -> embed
pipeline Owner uploads and End User /compare submissions already go
through), the one difference being these chunks ARE persisted to the
vector store, scoped to this Matter only.

chunk_id is namespaced by matter_id + uploaded_input_id + chunk_index
so the same filename uploaded to two different Matters (or twice to
the same Matter) never collides in chunk_embeddings.
"""

from typing import Optional

from app.analysis.ingestion import process_submission
from app.vector_store.base import VectorStore


def matter_namespace(matter_id: int) -> str:
    return f"matter-{matter_id}"


def ingest_matter_document(
    matter_id: int,
    uploaded_input_id,  # int for a client intake upload; "case-<id>" for an attorney case document
    filename: str,
    data: bytes,
    vector_store: Optional[VectorStore] = None,
    tenant_id: int = 1,
) -> int:
    """
    Chunk, embed, and store `data` under this Matter's namespace,
    tagged with `tenant_id` (the Matter's own tenant - see
    app/jobs/intake_processing.py's caller, which looks it up from
    metadata_repository.get_matter() before calling this) so the
    resulting chunks are invisible to every other tenant's retrieval,
    not just every other Matter's. Returns the number of chunks written.
    """

    from app.vector_store import get_vector_store

    vector_store = vector_store or get_vector_store()
    category = matter_namespace(matter_id)

    chunks = process_submission(filename, data)

    for chunk in chunks:
        vector_store.upsert_chunk_embedding(
            chunk_id=f"{category}:{uploaded_input_id}:{chunk['chunk_index']}",
            document_id=f"{category}:{uploaded_input_id}",
            category=category,
            filename=filename,
            chunk_text=chunk["text"],
            embedding=chunk["embedding"],
            model_name="all-MiniLM-L6-v2",
            chapter=chunk.get("chapter"),
            section=chunk.get("section"),
            start_page=chunk.get("start_page"),
            end_page=chunk.get("end_page"),
            tenant_id=tenant_id,
        )

    return len(chunks)
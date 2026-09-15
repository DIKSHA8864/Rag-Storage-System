"""
Vector store factory - the single place that decides which
VectorStore implementation the rest of the app talks to, mirroring
app/storage/__init__.py's get_storage_backend() and
app/metadata/__init__.py's get_metadata_repository().

Always PgVectorRepository today - pgvector on the same Postgres
already running for metadata (config/settings.py's postgres_dsn), no
separate vector database. Swap in a different backend later (Chroma,
a hosted vector DB) by editing get_vector_store() below; no caller
(app/jobs/processing.py, app/retrieval/) should need to change, since
they only ever call methods defined on VectorStore.
"""

from app.vector_store.base import VectorStore

_store_instance: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store_instance

    if _store_instance is None:
        from app.vector_store.vector_repository import PgVectorRepository
        from config.settings import get_settings

        _store_instance = PgVectorRepository(get_settings().postgres_dsn)

    return _store_instance

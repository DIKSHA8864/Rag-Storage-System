"""
Metadata repository factory - the single place that decides which
MetadataRepository implementation the rest of the app talks to,
mirroring app/storage/__init__.py's get_storage_backend() pattern.

Controlled by METADATA_BACKEND (config/settings.py / .env):
    "postgres" (default) -> PostgresMetadataRepository
    "sqlite"             -> SQLiteMetadataRepository (used by the test suite)
"""

from app.metadata.base import MetadataRepository

_repository_instance: MetadataRepository | None = None


def get_metadata_repository() -> MetadataRepository:
    global _repository_instance

    if _repository_instance is None:
        from config.settings import get_settings

        settings = get_settings()

        if settings.metadata_backend == "sqlite":
            from app.metadata.sqlite_repository import SQLiteMetadataRepository

            _repository_instance = SQLiteMetadataRepository(
                settings.resolve(settings.database_path)
            )
        else:
            from app.metadata.postgres_repository import PostgresMetadataRepository

            _repository_instance = PostgresMetadataRepository(settings.postgres_dsn)

    return _repository_instance

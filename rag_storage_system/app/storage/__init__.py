"""
Storage backend factory.

This is the single place that decides which StorageBackend
implementation the rest of the app talks to. Today it always returns
LocalStorageBackend (free, local disk). When you're ready to pay for
cloud storage:

    1. Write app/storage/s3_backend.py with a class S3StorageBackend
       that implements every method in app/storage/base.py
       (works for AWS S3, Cloudflare R2, and MinIO - all
       S3-compatible - with just different endpoint_url/credentials).
    2. For Azure Blob or Google Cloud Storage, write
       app/storage/azure_backend.py / gcs_backend.py instead, using
       their respective SDKs.
    3. Edit get_storage_backend() below to construct and return that
       class instead of LocalStorageBackend, reading connection
       details from environment variables / config/settings.py.

No caller (app/api/storage_api.py, ingestion_manager.py, etc.) should
need to change - they only ever call methods defined on
StorageBackend.
"""

from app.storage.base import StorageBackend
from app.storage.local_backend import LocalStorageBackend
from config.settings import get_settings

_settings = get_settings()

ORIGINALS_DIR = _settings.resolve(_settings.original_storage_path)
QUARANTINE_DIR = _settings.resolve(_settings.quarantine_storage_path)

_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """
    Returns the active storage backend (singleton).

    Swap the implementation here later - e.g.:

        from app.storage.s3_backend import S3StorageBackend
        return S3StorageBackend(bucket=os.environ["S3_BUCKET"], ...)
    """

    global _backend_instance

    if _backend_instance is None:
        _backend_instance = LocalStorageBackend(
            originals_dir=ORIGINALS_DIR,
            quarantine_dir=QUARANTINE_DIR,
        )

    return _backend_instance


_intake_backend_instance: StorageBackend | None = None


def get_intake_storage_backend() -> StorageBackend:
    """
    Separate storage backend for Client intake uploads
    (app/api/intake_api.py, app/jobs/intake_processing.py) - a
    different root directory (INTAKE_STORAGE_PATH) from the Owner's
    knowledge base (ORIGINAL_STORAGE_PATH above), so a Client's
    uploaded documents/images/audio/video/reports can never be
    confused with, or served alongside, the protected document
    repository.
    """

    global _intake_backend_instance

    if _intake_backend_instance is None:
        _intake_backend_instance = LocalStorageBackend(
            originals_dir=_settings.resolve(_settings.intake_storage_path),
            quarantine_dir=_settings.resolve(_settings.intake_quarantine_storage_path),
        )

    return _intake_backend_instance

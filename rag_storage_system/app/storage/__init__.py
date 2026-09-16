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
    Returns the active storage backend (singleton), chosen by
    STORAGE_BACKEND (config/settings.py):

        "local"  LocalStorageBackend - disk. The default, and what the
                 test suite uses (tests/conftest.py injects its own
                 instance pointed at tmp_path).
        "s3"     S3StorageBackend - MinIO locally, AWS S3 or
                 Cloudflare R2 in production. Imported lazily so boto3
                 is only needed when it's actually selected.
    """

    global _backend_instance

    if _backend_instance is None:
        if _settings.storage_backend == "s3":
            from app.storage.s3_backend import S3StorageBackend

            _backend_instance = S3StorageBackend(
                bucket=_settings.s3_bucket,
                quarantine_bucket=_settings.s3_quarantine_bucket,
                region=_settings.s3_region,
                endpoint_url=_settings.s3_endpoint_url,
                access_key_id=_settings.s3_access_key_id,
                secret_access_key=_settings.s3_secret_access_key,
            )
        else:
            _backend_instance = LocalStorageBackend(
                originals_dir=ORIGINALS_DIR,
                quarantine_dir=QUARANTINE_DIR,
            )

    return _backend_instance

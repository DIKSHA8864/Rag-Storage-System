"""
Storage backend interface.

Every place in the app that touches "where files live" should go
through an object that implements StorageBackend, instead of calling
shutil / pathlib directly. That is the whole point of this file: it
lets app/api/storage_api.py stay identical whether files are actually
sitting on local disk (LocalStorageBackend, used for the free demo)
or in S3 / Cloudflare R2 / Azure Blob / Google Cloud Storage / MinIO
later on.

To add a new backend later:
    1. Create app/storage/s3_backend.py (or r2_backend.py, etc.)
    2. Implement a class that subclasses StorageBackend and fills in
       every abstract method below.
    3. Change ONE line in app/storage/__init__.py (get_storage_backend)
       to return the new class instead of LocalStorageBackend.
No endpoint, schema, or calling code should need to change.

Design notes:
    - "category" is a folder path (e.g. "Contracts", or a nested
      subfolder "Contracts/2024"). Some
      backends organize files as bucket + key with no real folders
      (S3, R2), others have literal directories (local disk). The
      interface hides that difference: callers only ever think in
      terms of (category, filename).
    - Every method that stores or moves bytes returns a plain dict of
      metadata (filename actually stored under, size, sha256, etc.)
      rather than a backend-specific object (a Path, a boto3
      response, ...), so calling code never needs to know which
      backend answered.
    - Methods raise plain ValueError / FileNotFoundError / OSError.
      Backend-specific exceptions (botocore errors, etc.) should be
      caught and translated inside the backend implementation, not
      leaked to callers.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional


class StorageBackend(ABC):
    """Abstract base class for all storage backends."""

    # ------------------------------------------------------------------
    # Categories (folders)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_category(self, category: str) -> str:
        """
        Create a category if it doesn't already exist.

        Returns the sanitized category name actually used.
        """
        raise NotImplementedError

    @abstractmethod
    def list_categories(self) -> list[dict]:
        """
        Returns a list of {"name": str, "document_count": int}.
        """
        raise NotImplementedError

    @abstractmethod
    def rename_category(self, old_name: str, new_name: str) -> str:
        """
        Rename a category and everything stored under it.

        Returns the sanitized new category name.
        Raises FileNotFoundError if old_name doesn't exist, and
        ValueError if new_name already exists.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_category(self, category: str, force: bool = False) -> bool:
        """
        Delete a category.

        If force is False, raises ValueError when the category still
        has files in it (safety net against accidental bulk delete).
        Returns True if something was deleted, False if the category
        didn't exist.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    @abstractmethod
    def save(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        """
        Store file_obj under category/filename.

        Never overwrites an existing file - if the name is taken, the
        backend picks a non-colliding name (e.g. file_1.pdf).

        Returns a dict with at least:
            stored_filename, category, size, sha256
        """
        raise NotImplementedError

    @abstractmethod
    def replace(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        """
        Replace/update an existing file's contents in place, keeping
        the same filename. Raises FileNotFoundError if it doesn't
        already exist.

        Returns a dict with at least:
            stored_filename, category, size, sha256
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, category: str, filename: str) -> bool:
        """
        Delete one file. Returns True if it existed and was deleted,
        False if it didn't exist.
        """
        raise NotImplementedError

    @abstractmethod
    def exists(self, category: str, filename: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def open_file(self, category: str, filename: str) -> BinaryIO:
        """
        Open a stored file for reading (binary mode). Caller is
        responsible for closing it. Raises FileNotFoundError if it
        doesn't exist.
        """
        raise NotImplementedError

    @abstractmethod
    def list_files(self, category: Optional[str] = None) -> list[dict]:
        """
        List stored files, optionally filtered to one category.

        Returns a list of dicts with at least:
            filename, category, relative_path, extension, size
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Quarantine (files that failed validation)
    # ------------------------------------------------------------------

    @abstractmethod
    def quarantine(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        """
        Store a file that failed validation in quarantine instead of
        protected storage. Same return shape as save().
        """
        raise NotImplementedError

"""
Metadata repository interface.

Same abstraction principle as app/storage/base.py: everything that
tracks folders/documents in a database (not the files themselves - see
StorageBackend for that) goes through an object that implements
MetadataRepository, instead of any caller talking to sqlite3/psycopg
directly. app/api/storage_api.py only ever calls methods defined here,
so swapping SQLiteMetadataRepository for PostgresMetadataRepository -
or back, for a fast local/test run - is a factory change in
app/metadata/__init__.py, not an endpoint rewrite.
"""

from abc import ABC, abstractmethod
from typing import Optional


class MetadataRepository(ABC):
    """Abstract base class for all metadata repository backends."""

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    @abstractmethod
    def create_folder(self, path: str) -> None:
        """Ensure `path` and every ancestor folder has a row."""
        raise NotImplementedError

    @abstractmethod
    def rename_folder(self, old_path: str, new_path: str) -> None:
        """
        Rename/move a folder, cascading to every descendant folder and
        document whose path/category starts with `old_path`.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_folder(self, path: str) -> None:
        """Delete a folder, its descendant folders, and their documents."""
        raise NotImplementedError

    @abstractmethod
    def list_folders(self) -> list[dict]:
        """Returns a list of {"name": str, "document_count": int}."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    @abstractmethod
    def upsert_document(
        self,
        category: str,
        filename: str,
        extension: str,
        size: int,
        sha256: Optional[str],
        status: str = "Uploaded",
        status_detail: Optional[str] = None,
    ) -> None:
        """Insert a document row, or update it in place if it already exists."""
        raise NotImplementedError

    @abstractmethod
    def delete_document(self, category: str, filename: str) -> bool:
        """Returns True if a row existed and was deleted, False otherwise."""
        raise NotImplementedError

    @abstractmethod
    def get_document(self, category: str, filename: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_documents(self, category: Optional[str] = None) -> list[dict]:
        """List documents, optionally filtered to one category (including its subfolders)."""
        raise NotImplementedError

    @abstractmethod
    def update_document_status(
        self,
        category: str,
        filename: str,
        status: str,
        status_detail: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def update_status_where(self, old_status: str, new_status: str) -> int:
        """Bulk-transition every document in `old_status` to `new_status`. Returns the count changed."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Disclaimer
    # ------------------------------------------------------------------

    @abstractmethod
    def get_disclaimer(self) -> Optional[dict]:
        """
        Returns the Owner-edited disclaimer as
        {"text": str, "updated_at": ..., "updated_by": Optional[str]},
        or None if the Owner has never saved one yet.
        """
        raise NotImplementedError

    @abstractmethod
    def update_disclaimer(self, text: str, updated_by: Optional[str] = None) -> dict:
        """Create or replace the single disclaimer row and return it."""
        raise NotImplementedError
        # ------------------------------------------------------------------
    # Threads (isolated per matter - see app/matters.py)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_thread(self, matter_id: int, title: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_threads(self, matter_id: int) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_thread(self, thread_id: int, matter_id: int) -> Optional[dict]:
        """None if the thread doesn't exist OR belongs to a different matter - isolation lives here."""
        raise NotImplementedError

    @abstractmethod
    def add_thread_message(
        self, thread_id: int, role: str, content: str, sources_json: Optional[str] = None
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_thread_messages(self, thread_id: int) -> list[dict]:
        raise NotImplementedError
        @abstractmethod
    def get_active_prompt_version(self, name: str) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def list_prompt_versions(self, name: str) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def create_prompt_version(self, name: str, text: str, created_by: Optional[str] = None) -> dict:
        """Inserts the next version for `name`, deactivates the previous active one, activates this one."""
        raise NotImplementedError

    @abstractmethod
    def activate_prompt_version(self, name: str, version: int) -> dict:
        """Rollback/roll-forward: makes an existing version active again."""
        raise NotImplementedError
"""
PostgreSQL-backed metadata repository - the production backend, using
the fully normalized schema in database/migrations/. See
app/metadata/base.py for the interface this implements (identical to
SQLiteMetadataRepository's, by design - app/api/storage_api.py never
needs to know which one it's talking to).

Only `folders` and `documents` are read/written here today - the
other tables in the migration (users, document_versions, chunks,
embeddings, permissions, analysis_requests/reports, audit_logs) exist
so later features have a schema to land in, not because this
repository populates them yet.

One difference from the SQLite backend worth knowing: `created_at`/
`updated_at` come back as native Python `datetime` objects here
(Postgres TIMESTAMPTZ), not ISO strings (SQLite has no datetime type,
so that backend stores/returns TEXT). Nothing in this codebase reads
those two fields today, so it isn't a behavioral difference that
matters yet - flagged here so it doesn't surprise whoever adds the
first caller that does.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row

from app.metadata.base import MetadataRepository
from app.metadata.models import DocumentStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"


def _relative_path(category: str, filename: str) -> str:
    return f"{category}/{filename}"


def _ancestors(path: str) -> list[str]:
    """['Contracts/2024/Signed'] -> ['Contracts', 'Contracts/2024', 'Contracts/2024/Signed']"""

    parts = path.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _rewrite_prefix(value: str, old_prefix: str, new_prefix: str) -> str:
    if value == old_prefix:
        return new_prefix
    if value.startswith(old_prefix + "/"):
        return new_prefix + value[len(old_prefix):]
    return value


class PostgresMetadataRepository(MetadataRepository):

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """
        Every statement in database/migrations/*.sql is IF NOT
        EXISTS, so re-running them on every startup (same as the
        SQLite backend's CREATE TABLE IF NOT EXISTS in __init__) is
        safe and requires no separate migration-tracking table.
        """

        with self._connect() as conn:
            for migration_path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
                conn.execute(migration_path.read_text(encoding="utf-8"))

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def create_folder(self, path: str) -> None:
        """Ensure `path` and every ancestor folder has a row."""

        with self._connect() as conn:
            self.create_folder_conn(conn, path)

    def rename_folder(self, old_path: str, new_path: str) -> None:
        with self._connect() as conn:
            self.create_folder_conn(conn, new_path.rsplit("/", 1)[0] if "/" in new_path else "")

            rows = conn.execute(
                "SELECT path FROM folders WHERE path = %s OR path LIKE %s",
                (old_path, f"{old_path}/%"),
            ).fetchall()

            for row in rows:
                new_folder_path = _rewrite_prefix(row["path"], old_path, new_path)
                name = new_folder_path.rsplit("/", 1)[-1]
                parent_path = (
                    new_folder_path.rsplit("/", 1)[0] if "/" in new_folder_path else None
                )
                conn.execute(
                    """
                    INSERT INTO folders (path, name, parent_path)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        name = excluded.name,
                        parent_path = excluded.parent_path,
                        updated_at = now()
                    """,
                    (new_folder_path, name, parent_path),
                )
                conn.execute("DELETE FROM folders WHERE path = %s", (row["path"],))

            doc_rows = conn.execute(
                "SELECT relative_path, category, filename FROM documents "
                "WHERE category = %s OR category LIKE %s",
                (old_path, f"{old_path}/%"),
            ).fetchall()

            for row in doc_rows:
                new_category = _rewrite_prefix(row["category"], old_path, new_path)
                new_relative_path = _relative_path(new_category, row["filename"])
                conn.execute(
                    """
                    UPDATE documents
                    SET category = %s, relative_path = %s, updated_at = now()
                    WHERE relative_path = %s
                    """,
                    (new_category, new_relative_path, row["relative_path"]),
                )

    def create_folder_conn(self, conn: psycopg.Connection, path: str) -> None:
        if not path:
            return

        for ancestor in _ancestors(path):
            parent_path = ancestor.rsplit("/", 1)[0] if "/" in ancestor else None
            name = ancestor.rsplit("/", 1)[-1]

            conn.execute(
                """
                INSERT INTO folders (path, name, parent_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (path) DO NOTHING
                """,
                (ancestor, name, parent_path),
            )

    def delete_folder(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM documents WHERE category = %s OR category LIKE %s",
                (path, f"{path}/%"),
            )
            conn.execute(
                "DELETE FROM folders WHERE path = %s OR path LIKE %s",
                (path, f"{path}/%"),
            )

    def list_folders(self) -> list[dict]:
        with self._connect() as conn:
            folder_rows = conn.execute(
                "SELECT path FROM folders ORDER BY path"
            ).fetchall()

            folders = []

            for row in folder_rows:
                path = row["path"]
                count_row = conn.execute(
                    "SELECT COUNT(*) AS count FROM documents WHERE category = %s OR category LIKE %s",
                    (path, f"{path}/%"),
                ).fetchone()

                folders.append({"name": path, "document_count": count_row["count"]})

            return folders

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def upsert_document(
        self,
        category: str,
        filename: str,
        extension: str,
        size: int,
        sha256: Optional[str],
        status: str = DocumentStatus.UPLOADED.value,
        status_detail: Optional[str] = None,
    ) -> None:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            self.create_folder_conn(conn, category)

            conn.execute(
                """
                INSERT INTO documents (
                    category, filename, relative_path, extension, size,
                    sha256, status, status_detail
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (relative_path) DO UPDATE SET
                    category = excluded.category,
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size = excluded.size,
                    sha256 = excluded.sha256,
                    status = excluded.status,
                    status_detail = excluded.status_detail,
                    updated_at = now()
                """,
                (category, filename, relative_path, extension, size, sha256, status, status_detail),
            )

    def delete_document(self, category: str, filename: str) -> bool:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE relative_path = %s", (relative_path,)
            )
            return cursor.rowcount > 0

    def get_document(self, category: str, filename: str) -> Optional[dict]:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE relative_path = %s", (relative_path,)
            ).fetchone()

            return dict(row) if row else None

    def list_documents(self, category: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE category = %s OR category LIKE %s "
                    "ORDER BY relative_path",
                    (category, f"{category}/%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM documents ORDER BY relative_path"
                ).fetchall()

            return [dict(row) for row in rows]

    def update_document_status(
        self,
        category: str,
        filename: str,
        status: str,
        status_detail: Optional[str] = None,
    ) -> bool:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE documents
                SET status = %s, status_detail = %s, updated_at = now()
                WHERE relative_path = %s
                """,
                (status, status_detail, relative_path),
            )
            return cursor.rowcount > 0

    def update_status_where(self, old_status: str, new_status: str) -> int:
        """Bulk-transition every document in `old_status` to `new_status`."""

        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE documents SET status = %s, updated_at = now() WHERE status = %s",
                (new_status, old_status),
            )
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Disclaimer
    # ------------------------------------------------------------------

    def get_disclaimer(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text, updated_at, updated_by FROM disclaimer WHERE id = 1"
            ).fetchone()

            return dict(row) if row else None

    def update_disclaimer(self, text: str, updated_by: Optional[str] = None) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO disclaimer (id, text, updated_by)
                VALUES (1, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = now(),
                    updated_by = excluded.updated_by
                RETURNING text, updated_at, updated_by
                """,
                (text, updated_by),
            ).fetchone()

        return dict(row)

    # ------------------------------------------------------------------
    # Retrieval Settings
    # ------------------------------------------------------------------

    def get_retrieval_settings(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT top_k, score_threshold, min_chunks, updated_at, updated_by "
                "FROM retrieval_settings WHERE id = 1"
            ).fetchone()

            return dict(row) if row else None

    def update_retrieval_settings(
        self,
        top_k: int,
        score_threshold: float,
        min_chunks: int,
        updated_by: Optional[str] = None,
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO retrieval_settings (id, top_k, score_threshold, min_chunks, updated_by)
                VALUES (1, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    top_k = excluded.top_k,
                    score_threshold = excluded.score_threshold,
                    min_chunks = excluded.min_chunks,
                    updated_at = now(),
                    updated_by = excluded.updated_by
                RETURNING top_k, score_threshold, min_chunks, updated_at, updated_by
                """,
                (top_k, score_threshold, min_chunks, updated_by),
            ).fetchone()

        return dict(row)

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def create_thread(self, matter_id: int, title: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO threads (matter_id, title) VALUES (%s, %s) "
                "RETURNING id, matter_id, title, created_at, updated_at",
                (matter_id, title),
            ).fetchone()
        return dict(row)

    def list_threads(self, matter_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE matter_id = %s ORDER BY updated_at DESC", (matter_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_thread(self, thread_id: int, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM threads WHERE id = %s AND matter_id = %s", (thread_id, matter_id)
            ).fetchone()
        return dict(row) if row else None

    def add_thread_message(
        self, thread_id: int, role: str, content: str, sources_json: Optional[str] = None
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO thread_messages (thread_id, role, content, sources_json) "
                "VALUES (%s, %s, %s, %s) "
                "RETURNING id, thread_id, role, content, sources_json, created_at",
                (thread_id, role, content, sources_json),
            ).fetchone()
            conn.execute("UPDATE threads SET updated_at = now() WHERE id = %s", (thread_id,))
        return dict(row)

    def list_thread_messages(self, thread_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_messages WHERE thread_id = %s ORDER BY id", (thread_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Matters
    # ------------------------------------------------------------------

    def get_matter_by_key_hash(self, api_key_hash: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM matters WHERE api_key_hash = %s AND is_active = TRUE", (api_key_hash,)
            ).fetchone()
        return dict(row) if row else None

    def create_matter(self, name: str, api_key_hash: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO matters (name, api_key_hash) VALUES (%s, %s) "
                "RETURNING id, name, api_key_hash, is_active, created_at",
                (name, api_key_hash),
            ).fetchone()
        return dict(row)

    def list_matters(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM matters ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Prompt Versions
    # ------------------------------------------------------------------

    def get_active_prompt_version(self, name: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE name = %s AND is_active = TRUE", (name,)
            ).fetchone()
        return dict(row) if row else None

    def list_prompt_versions(self, name: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE name = %s ORDER BY version DESC", (name,)
            ).fetchall()
        return [dict(row) for row in rows]

    def create_prompt_version(self, name: str, text: str, created_by: Optional[str] = None) -> dict:
        with self._connect() as conn:
            next_version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM prompt_versions WHERE name = %s",
                (name,),
            ).fetchone()["next_version"]

            conn.execute("UPDATE prompt_versions SET is_active = FALSE WHERE name = %s", (name,))
            row = conn.execute(
                "INSERT INTO prompt_versions (name, version, text, is_active, created_by) "
                "VALUES (%s, %s, %s, TRUE, %s) "
                "RETURNING name, version, text, is_active, created_at, created_by",
                (name, next_version, text, created_by),
            ).fetchone()
        return dict(row)

    def activate_prompt_version(self, name: str, version: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE name = %s AND version = %s", (name, version)
            ).fetchone()
            if row is None:
                raise ValueError(f"No such prompt version: {name} v{version}")

            conn.execute("UPDATE prompt_versions SET is_active = FALSE WHERE name = %s", (name,))
            conn.execute(
                "UPDATE prompt_versions SET is_active = TRUE WHERE name = %s AND version = %s",
                (name, version),
            )
        return dict(row)

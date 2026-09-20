"""
SQLite-backed metadata repository - the fast, zero-setup backend used
for local development and the test suite. See app/metadata/base.py for
the interface this implements, and postgres_repository.py for the
production backend with the fully normalized schema
(database/migrations/0001_initial_schema.sql).

Every method opens and closes its own connection. That is simpler than
sharing one connection across FastAPI's threadpool and is fast enough
at demo/test scale.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.metadata.base import MetadataRepository
from app.metadata.models import DocumentStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    extension TEXT,
    size INTEGER,
    sha256 TEXT,
    status TEXT NOT NULL,
    status_detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS disclaimer (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    text TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    created_by TEXT,
    UNIQUE (name, version)
);
CREATE TABLE IF NOT EXISTS matters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    api_key_hash TEXT UNIQUE NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    top_k INTEGER NOT NULL,
    score_threshold REAL NOT NULL,
    min_chunks INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class SQLiteMetadataRepository(MetadataRepository):

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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
        now = _now()

        with self._connect() as conn:
            self.create_folder_conn(conn, new_path.rsplit("/", 1)[0] if "/" in new_path else "")

            rows = conn.execute(
                "SELECT path FROM folders WHERE path = ? OR path LIKE ?",
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
                    INSERT INTO folders (path, name, parent_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        name = excluded.name,
                        parent_path = excluded.parent_path,
                        updated_at = excluded.updated_at
                    """,
                    (new_folder_path, name, parent_path, now, now),
                )
                conn.execute("DELETE FROM folders WHERE path = ?", (row["path"],))

            doc_rows = conn.execute(
                "SELECT relative_path, category, filename FROM documents "
                "WHERE category = ? OR category LIKE ?",
                (old_path, f"{old_path}/%"),
            ).fetchall()

            for row in doc_rows:
                new_category = _rewrite_prefix(row["category"], old_path, new_path)
                new_relative_path = _relative_path(new_category, row["filename"])
                conn.execute(
                    """
                    UPDATE documents
                    SET category = ?, relative_path = ?, updated_at = ?
                    WHERE relative_path = ?
                    """,
                    (new_category, new_relative_path, now, row["relative_path"]),
                )

    def create_folder_conn(self, conn: sqlite3.Connection, path: str) -> None:
        if not path:
            return

        now = _now()

        for ancestor in _ancestors(path):
            parent_path = ancestor.rsplit("/", 1)[0] if "/" in ancestor else None
            name = ancestor.rsplit("/", 1)[-1]

            conn.execute(
                """
                INSERT INTO folders (path, name, parent_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO NOTHING
                """,
                (ancestor, name, parent_path, now, now),
            )

    def delete_folder(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM documents WHERE category = ? OR category LIKE ?",
                (path, f"{path}/%"),
            )
            conn.execute(
                "DELETE FROM folders WHERE path = ? OR path LIKE ?",
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
                count = conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE category = ? OR category LIKE ?",
                    (path, f"{path}/%"),
                ).fetchone()[0]

                folders.append({"name": path, "document_count": count})

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
        now = _now()
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            self.create_folder_conn(conn, category)

            conn.execute(
                """
                INSERT INTO documents (
                    category, filename, relative_path, extension, size,
                    sha256, status, status_detail, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relative_path) DO UPDATE SET
                    category = excluded.category,
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size = excluded.size,
                    sha256 = excluded.sha256,
                    status = excluded.status,
                    status_detail = excluded.status_detail,
                    updated_at = excluded.updated_at
                """,
                (
                    category, filename, relative_path, extension, size,
                    sha256, status, status_detail, now, now,
                ),
            )

    def delete_document(self, category: str, filename: str) -> bool:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE relative_path = ?", (relative_path,)
            )
            return cursor.rowcount > 0

    def get_document(self, category: str, filename: str) -> Optional[dict]:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE relative_path = ?", (relative_path,)
            ).fetchone()

            return dict(row) if row else None

    def list_documents(self, category: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE category = ? OR category LIKE ? "
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
        now = _now()

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE documents
                SET status = ?, status_detail = ?, updated_at = ?
                WHERE relative_path = ?
                """,
                (status, status_detail, now, relative_path),
            )
            return cursor.rowcount > 0

    def update_status_where(self, old_status: str, new_status: str) -> int:
        """Bulk-transition every document in `old_status` to `new_status`."""

        now = _now()

        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE documents SET status = ?, updated_at = ? WHERE status = ?",
                (new_status, now, old_status),
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
        now = _now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO disclaimer (id, text, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (text, now, updated_by),
            )

        return {"text": text, "updated_at": now, "updated_by": updated_by}

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
        now = _now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_settings
                    (id, top_k, score_threshold, min_chunks, updated_at, updated_by)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    top_k = excluded.top_k,
                    score_threshold = excluded.score_threshold,
                    min_chunks = excluded.min_chunks,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (top_k, score_threshold, min_chunks, now, updated_by),
            )

        return {
            "top_k": top_k,
            "score_threshold": score_threshold,
            "min_chunks": min_chunks,
            "updated_at": now,
            "updated_by": updated_by,
        }

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def create_thread(self, matter_id: int, title: str) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO threads (matter_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (matter_id, title, now, now),
            )
            return {"id": cursor.lastrowid, "matter_id": matter_id, "title": title, "created_at": now, "updated_at": now}

    def list_threads(self, matter_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE matter_id = ? ORDER BY updated_at DESC", (matter_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_thread(self, thread_id: int, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM threads WHERE id = ? AND matter_id = ?", (thread_id, matter_id)
            ).fetchone()
            return dict(row) if row else None

    def add_thread_message(
        self, thread_id: int, role: str, content: str, sources_json: Optional[str] = None
    ) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO thread_messages (thread_id, role, content, sources_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (thread_id, role, content, sources_json, now),
            )
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
            return {
                "id": cursor.lastrowid, "thread_id": thread_id, "role": role,
                "content": content, "sources_json": sources_json, "created_at": now,
            }

    def list_thread_messages(self, thread_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_messages WHERE thread_id = ? ORDER BY id", (thread_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Matters
    # ------------------------------------------------------------------

    def get_matter_by_key_hash(self, api_key_hash: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM matters WHERE api_key_hash = ? AND is_active = 1", (api_key_hash,)
            ).fetchone()
            return dict(row) if row else None

    def create_matter(self, name: str, api_key_hash: str) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO matters (name, api_key_hash, is_active, created_at) VALUES (?, ?, 1, ?)",
                (name, api_key_hash, now),
            )
            return {
                "id": cursor.lastrowid, "name": name, "api_key_hash": api_key_hash,
                "is_active": True, "created_at": now,
            }

    def list_matters(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM matters ORDER BY name").fetchall()]

    # ------------------------------------------------------------------
    # Prompt Versions
    # ------------------------------------------------------------------

    def get_active_prompt_version(self, name: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE name = ? AND is_active = 1", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_prompt_versions(self, name: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE name = ? ORDER BY version DESC", (name,)
            ).fetchall()
            return [dict(row) for row in rows]

    def create_prompt_version(self, name: str, text: str, created_by: Optional[str] = None) -> dict:
        now = _now()
        with self._connect() as conn:
            next_version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE name = ?", (name,)
            ).fetchone()[0]

            conn.execute("UPDATE prompt_versions SET is_active = 0 WHERE name = ?", (name,))
            conn.execute(
                "INSERT INTO prompt_versions (name, version, text, is_active, created_at, created_by) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (name, next_version, text, now, created_by),
            )
            return {
                "name": name, "version": next_version, "text": text, "is_active": True,
                "created_at": now, "created_by": created_by,
            }

    def activate_prompt_version(self, name: str, version: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE name = ? AND version = ?", (name, version)
            ).fetchone()
            if row is None:
                raise ValueError(f"No such prompt version: {name} v{version}")

            conn.execute("UPDATE prompt_versions SET is_active = 0 WHERE name = ?", (name,))
            conn.execute(
                "UPDATE prompt_versions SET is_active = 1 WHERE name = ? AND version = ?", (name, version)
            )
            return dict(row)

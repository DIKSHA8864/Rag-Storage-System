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

    def create_folder(self, path: str, tenant_id: int = 1) -> None:
        """Ensure `path` and every ancestor folder has a row."""

        with self._connect() as conn:
            self.create_folder_conn(conn, path, tenant_id)

    def rename_folder(self, old_path: str, new_path: str, tenant_id: int = 1) -> None:
        with self._connect() as conn:
            self.create_folder_conn(
                conn, new_path.rsplit("/", 1)[0] if "/" in new_path else "", tenant_id
            )

            rows = conn.execute(
                "SELECT path FROM folders WHERE tenant_id = %s AND (path = %s OR path LIKE %s)",
                (tenant_id, old_path, f"{old_path}/%"),
            ).fetchall()

            for row in rows:
                new_folder_path = _rewrite_prefix(row["path"], old_path, new_path)
                name = new_folder_path.rsplit("/", 1)[-1]
                parent_path = (
                    new_folder_path.rsplit("/", 1)[0] if "/" in new_folder_path else None
                )
                conn.execute(
                    """
                    INSERT INTO folders (tenant_id, path, name, parent_path)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (tenant_id, path) DO UPDATE SET
                        name = excluded.name,
                        parent_path = excluded.parent_path,
                        updated_at = now()
                    """,
                    (tenant_id, new_folder_path, name, parent_path),
                )
                conn.execute(
                    "DELETE FROM folders WHERE tenant_id = %s AND path = %s", (tenant_id, row["path"])
                )

            doc_rows = conn.execute(
                "SELECT relative_path, category, filename FROM documents "
                "WHERE tenant_id = %s AND (category = %s OR category LIKE %s)",
                (tenant_id, old_path, f"{old_path}/%"),
            ).fetchall()

            for row in doc_rows:
                new_category = _rewrite_prefix(row["category"], old_path, new_path)
                new_relative_path = _relative_path(new_category, row["filename"])
                conn.execute(
                    """
                    UPDATE documents
                    SET category = %s, relative_path = %s, updated_at = now()
                    WHERE tenant_id = %s AND relative_path = %s
                    """,
                    (new_category, new_relative_path, tenant_id, row["relative_path"]),
                )

    def create_folder_conn(self, conn: psycopg.Connection, path: str, tenant_id: int = 1) -> None:
        if not path:
            return

        for ancestor in _ancestors(path):
            parent_path = ancestor.rsplit("/", 1)[0] if "/" in ancestor else None
            name = ancestor.rsplit("/", 1)[-1]

            conn.execute(
                """
                INSERT INTO folders (tenant_id, path, name, parent_path)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, path) DO NOTHING
                """,
                (tenant_id, ancestor, name, parent_path),
            )

    def delete_folder(self, path: str, tenant_id: int = 1) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM documents WHERE tenant_id = %s AND (category = %s OR category LIKE %s)",
                (tenant_id, path, f"{path}/%"),
            )
            conn.execute(
                "DELETE FROM folders WHERE tenant_id = %s AND (path = %s OR path LIKE %s)",
                (tenant_id, path, f"{path}/%"),
            )

    def list_folders(self, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            folder_rows = conn.execute(
                "SELECT path FROM folders WHERE tenant_id = %s ORDER BY path", (tenant_id,)
            ).fetchall()

            folders = []

            for row in folder_rows:
                path = row["path"]
                count_row = conn.execute(
                    "SELECT COUNT(*) AS count FROM documents WHERE tenant_id = %s AND (category = %s OR category LIKE %s)",
                    (tenant_id, path, f"{path}/%"),
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
        tenant_id: int = 1,
    ) -> None:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            self.create_folder_conn(conn, category, tenant_id)

            conn.execute(
                """
                INSERT INTO documents (
                    tenant_id, category, filename, relative_path, extension, size,
                    sha256, status, status_detail
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, relative_path) DO UPDATE SET
                    category = excluded.category,
                    filename = excluded.filename,
                    extension = excluded.extension,
                    size = excluded.size,
                    sha256 = excluded.sha256,
                    status = excluded.status,
                    status_detail = excluded.status_detail,
                    updated_at = now()
                """,
                (tenant_id, category, filename, relative_path, extension, size, sha256, status, status_detail),
            )

    def delete_document(self, category: str, filename: str, tenant_id: int = 1) -> bool:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE tenant_id = %s AND relative_path = %s", (tenant_id, relative_path)
            )
            return cursor.rowcount > 0

    def get_document(self, category: str, filename: str, tenant_id: int = 1) -> Optional[dict]:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE tenant_id = %s AND relative_path = %s", (tenant_id, relative_path)
            ).fetchone()

            return dict(row) if row else None

    def list_documents(self, category: Optional[str] = None, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE tenant_id = %s AND (category = %s OR category LIKE %s) "
                    "ORDER BY relative_path",
                    (tenant_id, category, f"{category}/%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE tenant_id = %s ORDER BY relative_path", (tenant_id,)
                ).fetchall()

            return [dict(row) for row in rows]

    def update_document_status(
        self,
        category: str,
        filename: str,
        status: str,
        status_detail: Optional[str] = None,
        tenant_id: int = 1,
    ) -> bool:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE documents
                SET status = %s, status_detail = %s, updated_at = now()
                WHERE tenant_id = %s AND relative_path = %s
                """,
                (status, status_detail, tenant_id, relative_path),
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

    # Per organization (migration 0020). The old single-row tables are
    # the Default Organization's fallback until it saves its own.

    def get_disclaimer(self, tenant_id: int = 1) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text, updated_at, updated_by FROM tenant_disclaimers WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()
            if row is None and tenant_id == 1:
                row = conn.execute("SELECT text, updated_at, updated_by FROM disclaimer WHERE id = 1").fetchone()

            return dict(row) if row else None

    def update_disclaimer(self, text: str, updated_by: Optional[str] = None, tenant_id: int = 1) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO tenant_disclaimers (tenant_id, text, updated_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = now(),
                    updated_by = excluded.updated_by
                RETURNING text, updated_at, updated_by
                """,
                (tenant_id, text, updated_by),
            ).fetchone()

        return dict(row)

    # ------------------------------------------------------------------
    # Retrieval Settings
    # ------------------------------------------------------------------

    def get_retrieval_settings(self, tenant_id: int = 1) -> Optional[dict]:
        columns = "top_k, score_threshold, min_chunks, updated_at, updated_by"
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {columns} FROM tenant_retrieval_settings WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()
            if row is None and tenant_id == 1:
                row = conn.execute(f"SELECT {columns} FROM retrieval_settings WHERE id = 1").fetchone()

            return dict(row) if row else None

    def update_retrieval_settings(
        self,
        top_k: int,
        score_threshold: float,
        min_chunks: int,
        updated_by: Optional[str] = None,
        tenant_id: int = 1,
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO tenant_retrieval_settings (tenant_id, top_k, score_threshold, min_chunks, updated_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    top_k = excluded.top_k,
                    score_threshold = excluded.score_threshold,
                    min_chunks = excluded.min_chunks,
                    updated_at = now(),
                    updated_by = excluded.updated_by
                RETURNING top_k, score_threshold, min_chunks, updated_at, updated_by
                """,
                (tenant_id, top_k, score_threshold, min_chunks, updated_by),
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

    def create_matter(self, name: str, api_key_hash: str, tenant_id: int = 1) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO matters (tenant_id, name, api_key_hash) VALUES (%s, %s, %s) "
                "RETURNING id, tenant_id, name, api_key_hash, is_active, created_at",
                (tenant_id, name, api_key_hash),
            ).fetchone()
        return dict(row)

    def list_matters(self, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM matters WHERE tenant_id = %s ORDER BY name", (tenant_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_matter(self, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM matters WHERE id = %s", (matter_id,)).fetchone()
        return dict(row) if row else None

    def create_matter_assignment(self, owner_id: int, matter_id: int, role: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO matter_assignments (owner_id, matter_id, role) VALUES (%s, %s, %s)
                ON CONFLICT (owner_id, matter_id) DO UPDATE SET role = excluded.role
                RETURNING id, owner_id, matter_id, role, assigned_at
                """,
                (owner_id, matter_id, role),
            ).fetchone()
        return dict(row)

    def get_matter_assignment(self, owner_id: int, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM matter_assignments WHERE owner_id = %s AND matter_id = %s", (owner_id, matter_id)
            ).fetchone()
        return dict(row) if row else None

    def list_assignments_for_matter(self, matter_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM matter_assignments WHERE matter_id = %s", (matter_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    # ------------------------------------------------------------------
    # Prompt Versions
    # ------------------------------------------------------------------

    def get_active_prompt_version(self, name: str, tenant_id: int = 1) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE tenant_id = %s AND name = %s AND is_active = TRUE",
                (tenant_id, name),
            ).fetchone()
        return dict(row) if row else None

    def list_prompt_versions(self, name: str, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE tenant_id = %s AND name = %s ORDER BY version DESC",
                (tenant_id, name),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_prompt_version(
        self, name: str, text: str, created_by: Optional[str] = None, tenant_id: int = 1
    ) -> dict:
        with self._connect() as conn:
            next_version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM prompt_versions "
                "WHERE tenant_id = %s AND name = %s",
                (tenant_id, name),
            ).fetchone()["next_version"]

            conn.execute(
                "UPDATE prompt_versions SET is_active = FALSE WHERE tenant_id = %s AND name = %s",
                (tenant_id, name),
            )
            row = conn.execute(
                "INSERT INTO prompt_versions (tenant_id, name, version, text, is_active, created_by) "
                "VALUES (%s, %s, %s, %s, TRUE, %s) "
                "RETURNING tenant_id, name, version, text, is_active, created_at, created_by",
                (tenant_id, name, next_version, text, created_by),
            ).fetchone()
        return dict(row)

    def activate_prompt_version(self, name: str, version: int, tenant_id: int = 1) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE tenant_id = %s AND name = %s AND version = %s",
                (tenant_id, name, version),
            ).fetchone()
            if row is None:
                raise ValueError(f"No such prompt version: {name} v{version}")

            conn.execute(
                "UPDATE prompt_versions SET is_active = FALSE WHERE tenant_id = %s AND name = %s",
                (tenant_id, name),
            )
            conn.execute(
                "UPDATE prompt_versions SET is_active = TRUE WHERE tenant_id = %s AND name = %s AND version = %s",
                (tenant_id, name, version),
            )
        return dict(row)

    # ------------------------------------------------------------------
    # Intake Sessions
    # ------------------------------------------------------------------

    def create_intake_session(self, matter_id: int, title: str, thread_id: Optional[int] = None) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO intake_sessions (matter_id, thread_id, title) VALUES (%s, %s, %s) "
                "RETURNING id, matter_id, thread_id, title, status, created_at, updated_at",
                (matter_id, thread_id, title),
            ).fetchone()
        return dict(row)

    def list_intake_sessions(self, matter_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_sessions WHERE matter_id = %s ORDER BY updated_at DESC", (matter_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_intake_session(self, session_id: int, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM intake_sessions WHERE id = %s AND matter_id = %s", (session_id, matter_id)
            ).fetchone()
        return dict(row) if row else None

    def get_intake_session_by_id(self, session_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM intake_sessions WHERE id = %s", (session_id,)).fetchone()
        return dict(row) if row else None

    def update_intake_session_status(self, session_id: int, status: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE intake_sessions SET status = %s, updated_at = now() WHERE id = %s", (status, session_id)
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Uploaded Inputs
    # ------------------------------------------------------------------

    def create_uploaded_input(
        self,
        intake_session_id: int,
        matter_id: int,
        original_filename: str,
        stored_category: str,
        stored_filename: str,
        media_type: str,
        size: int,
        sha256: Optional[str],
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO uploaded_inputs (
                    intake_session_id, matter_id, original_filename, stored_category, stored_filename, media_type, size, sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, intake_session_id, matter_id, original_filename, stored_category, stored_filename,
                          media_type, size, sha256, processing_status, status_detail, created_at, updated_at
                """,
                (intake_session_id, matter_id, original_filename, stored_category, stored_filename, media_type, size, sha256),
            ).fetchone()
        return dict(row)

    def get_uploaded_input(self, input_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM uploaded_inputs WHERE id = %s", (input_id,)).fetchone()
        return dict(row) if row else None

    def list_uploaded_inputs(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM uploaded_inputs WHERE intake_session_id = %s ORDER BY id", (intake_session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_uploaded_input_status(
        self, input_id: int, processing_status: str, status_detail: Optional[str] = None
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE uploaded_inputs SET processing_status = %s, status_detail = %s, updated_at = now() WHERE id = %s",
                (processing_status, status_detail, input_id),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Extracted Information
    # ------------------------------------------------------------------

    def add_extracted_information(
        self,
        uploaded_input_id: int,
        content_type: str,
        text: str,
        provider: str,
        is_mock: bool,
        archive_member_filename: Optional[str] = None,
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO extracted_information (
                    uploaded_input_id, archive_member_filename, content_type, text, provider, is_mock
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, uploaded_input_id, archive_member_filename, content_type, text, provider, is_mock, created_at
                """,
                (uploaded_input_id, archive_member_filename, content_type, text, provider, is_mock),
            ).fetchone()
        return dict(row)

    def list_extracted_information(self, uploaded_input_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM extracted_information WHERE uploaded_input_id = %s ORDER BY id", (uploaded_input_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def add_timeline_event(self, intake_session_id: int, event_type: str, description: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO timeline_events (intake_session_id, event_type, description) VALUES (%s, %s, %s) "
                "RETURNING id, intake_session_id, event_type, description, created_at",
                (intake_session_id, event_type, description),
            ).fetchone()
        return dict(row)

    def list_timeline_events(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM timeline_events WHERE intake_session_id = %s ORDER BY id", (intake_session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def create_report(
        self, intake_session_id: int, matter_id: int, format: str, stored_category: str, stored_filename: str
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO reports (intake_session_id, matter_id, format, stored_category, stored_filename) "
                "VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id, intake_session_id, matter_id, format, stored_category, stored_filename, created_at",
                (intake_session_id, matter_id, format, stored_category, stored_filename),
            ).fetchone()
        return dict(row)

    def get_report(self, report_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = %s", (report_id,)).fetchone()
        return dict(row) if row else None

    def list_reports(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reports WHERE intake_session_id = %s ORDER BY id", (intake_session_id,)
            ).fetchall()
        return [dict(row) for row in rows]
        # ------------------------------------------------------------------
    # Guided Intake Engine - Interview State
    # ------------------------------------------------------------------
        # ------------------------------------------------------------------
    # Report Review Queue
    # ------------------------------------------------------------------

    def create_report_review(self, report_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO report_reviews (report_id) VALUES (%s) "
                "RETURNING id, report_id, status, reviewed_by, reviewed_at, rejection_reason, created_at, updated_at",
                (report_id,),
            ).fetchone()
        return dict(row)

    def get_report_review(self, report_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM report_reviews WHERE report_id = %s", (report_id,)).fetchone()
        return dict(row) if row else None

    def list_report_reviews(self, status: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM report_reviews WHERE status = %s ORDER BY id", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM report_reviews ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def update_report_review(
        self, report_id: int, status: str, reviewed_by: Optional[str] = None, rejection_reason: Optional[str] = None
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE report_reviews
                SET status = %s, reviewed_by = %s, reviewed_at = now(), rejection_reason = %s, updated_at = now()
                WHERE report_id = %s
                RETURNING id, report_id, status, reviewed_by, reviewed_at, rejection_reason, created_at, updated_at
                """,
                (status, reviewed_by, rejection_reason, report_id),
            ).fetchone()
        return dict(row)

        # ------------------------------------------------------------------
    # Cause of Action Library
    # ------------------------------------------------------------------

    def create_cause_of_action(
        self, category: str, name: str, elements: list[str], authority_citation: str, tenant_id: int = 1
    ) -> dict:
        from psycopg.types.json import Jsonb

        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO cause_of_action_library (category, name, elements, authority_citation, tenant_id) "
                "VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id, category, name, elements, authority_citation, created_at, tenant_id",
                (category, name, Jsonb(elements), authority_citation, tenant_id),
            ).fetchone()
        return dict(row)

    def get_cause_of_action(self, cause_of_action_id: int, tenant_id: int = 1) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cause_of_action_library WHERE id = %s AND tenant_id = %s",
                (cause_of_action_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def list_causes_of_action(self, category: Optional[str] = None, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM cause_of_action_library WHERE category = %s AND tenant_id = %s ORDER BY id",
                    (category, tenant_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cause_of_action_library WHERE tenant_id = %s ORDER BY id", (tenant_id,)
                ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------

    def create_complaint(
        self,
        intake_session_id: int,
        matter_id: int,
        format: str,
        cause_of_action_ids: list[int],
        stored_category: str,
        stored_filename: str,
    ) -> dict:
        from psycopg.types.json import Jsonb

        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO complaints (
                    intake_session_id, matter_id, format, cause_of_action_ids, stored_category, stored_filename
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, intake_session_id, matter_id, format, cause_of_action_ids,
                          stored_category, stored_filename, created_at
                """,
                (intake_session_id, matter_id, format, Jsonb(cause_of_action_ids), stored_category, stored_filename),
            ).fetchone()
        return dict(row)

    def get_complaint(self, complaint_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM complaints WHERE id = %s", (complaint_id,)).fetchone()
        return dict(row) if row else None

    def list_complaints(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM complaints WHERE intake_session_id = %s ORDER BY id", (intake_session_id,)
            ).fetchall()
        return [dict(row) for row in rows]
    def create_interview_state(self, intake_session_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO interview_state (intake_session_id)
                VALUES (%s)
                RETURNING id, intake_session_id, language, terms_accepted_at, terms_version,
                          current_state, current_step_index, mandatory_sweep_completed, created_at, updated_at
                """,
                (intake_session_id,),
            ).fetchone()
        return dict(row)

    def get_interview_state(self, intake_session_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM interview_state WHERE intake_session_id = %s", (intake_session_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_interview_state(
        self,
        intake_session_id: int,
        language: Optional[str],
        current_state: str,
        current_step_index: int,
        terms_accepted_at: Optional[str],
        terms_version: Optional[str],
        mandatory_sweep_completed: bool,
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE interview_state
                SET language = %s, current_state = %s, current_step_index = %s,
                    terms_accepted_at = %s, terms_version = %s, mandatory_sweep_completed = %s, updated_at = now()
                WHERE intake_session_id = %s
                RETURNING id, intake_session_id, language, terms_accepted_at, terms_version,
                          current_state, current_step_index, mandatory_sweep_completed, created_at, updated_at
                """,
                (language, current_state, current_step_index, terms_accepted_at, terms_version,
                 mandatory_sweep_completed, intake_session_id),
            ).fetchone()
        return dict(row)

    # ------------------------------------------------------------------
    # Guided Intake Engine - Messages
    # ------------------------------------------------------------------

    def add_intake_message(self, intake_session_id: int, role: str, content: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO intake_messages (intake_session_id, role, content) VALUES (%s, %s, %s) "
                "RETURNING id, intake_session_id, role, content, created_at",
                (intake_session_id, role, content),
            ).fetchone()
        return dict(row)

    def list_intake_messages(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_messages WHERE intake_session_id = %s ORDER BY id", (intake_session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Guided Intake Engine - Facts
    # ------------------------------------------------------------------

    def add_intake_fact(self, intake_session_id: int, category: str, fact_key: str, fact_value: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO intake_facts (intake_session_id, category, fact_key, fact_value) VALUES (%s, %s, %s, %s) "
                "RETURNING id, intake_session_id, category, fact_key, fact_value, created_at",
                (intake_session_id, category, fact_key, fact_value),
            ).fetchone()
        return dict(row)

    def list_intake_facts(self, intake_session_id: int, category: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM intake_facts WHERE intake_session_id = %s AND category = %s ORDER BY id",
                    (intake_session_id, category),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM intake_facts WHERE intake_session_id = %s ORDER BY id", (intake_session_id,)
                ).fetchall()
        return [dict(row) for row in rows]

    def add_llm_usage_log(
        self, matter_id, intake_session_id, purpose, model, input_tokens, output_tokens, latency_ms,
        query_text=None, retrieved_chunk_ids=None, retrieved_chunk_scores=None, citation_check_result=None,
        tenant_id: int = 1,
    ) -> dict:
        import json

        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO llm_usage_log (matter_id, intake_session_id, purpose, model, "
                "input_tokens, output_tokens, latency_ms, query_text, retrieved_chunk_ids, "
                "retrieved_chunk_scores, citation_check_result, tenant_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING *",
                (
                    matter_id, intake_session_id, purpose, model, input_tokens, output_tokens, latency_ms,
                    query_text,
                    json.dumps(retrieved_chunk_ids) if retrieved_chunk_ids is not None else None,
                    json.dumps(retrieved_chunk_scores) if retrieved_chunk_scores is not None else None,
                    citation_check_result, tenant_id,
                ),
            ).fetchone()
        return dict(row)

    # ------------------------------------------------------------------
    # Owner research threads
    # ------------------------------------------------------------------

    _THREAD_COLUMNS = "id, tenant_id, owner_sub, title, created_at, updated_at"

    def create_research_thread(self, tenant_id: int, owner_sub: str, title: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                f"INSERT INTO research_threads (tenant_id, owner_sub, title) VALUES (%s, %s, %s) "
                f"RETURNING {self._THREAD_COLUMNS}",
                (tenant_id, owner_sub, title),
            ).fetchone()
        return dict(row)

    def list_research_threads(self, tenant_id: int, owner_sub: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.tenant_id, t.owner_sub, t.title, t.created_at, t.updated_at,
                       COUNT(m.id) AS message_count
                FROM research_threads t LEFT JOIN research_messages m ON m.thread_id = t.id
                WHERE t.tenant_id = %s AND t.owner_sub = %s
                GROUP BY t.id
                ORDER BY t.updated_at DESC, t.id DESC
                """,
                (tenant_id, owner_sub),
            ).fetchall()
        return [{**dict(r), "message_count": int(r["message_count"])} for r in rows]

    def get_research_thread(self, thread_id: int, tenant_id: int, owner_sub: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._THREAD_COLUMNS} FROM research_threads WHERE id = %s AND tenant_id = %s AND owner_sub = %s",
                (thread_id, tenant_id, owner_sub),
            ).fetchone()
        return dict(row) if row else None

    def rename_research_thread(self, thread_id: int, tenant_id: int, owner_sub: str, title: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                f"UPDATE research_threads SET title = %s, updated_at = now() "
                f"WHERE id = %s AND tenant_id = %s AND owner_sub = %s RETURNING {self._THREAD_COLUMNS}",
                (title, thread_id, tenant_id, owner_sub),
            ).fetchone()
        return dict(row) if row else None

    def delete_research_thread(self, thread_id: int, tenant_id: int, owner_sub: str) -> bool:
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM research_threads WHERE id = %s AND tenant_id = %s AND owner_sub = %s",
                (thread_id, tenant_id, owner_sub),
            ).rowcount
        return deleted > 0

    def add_research_exchange(self, thread_id: int, question: str, answer: str, sources: list[dict]) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_messages (thread_id, role, content) VALUES (%s, 'user', %s)",
                (thread_id, question),
            )
            conn.execute(
                "INSERT INTO research_messages (thread_id, role, content, sources) VALUES (%s, 'assistant', %s, %s)",
                (thread_id, answer, Jsonb(sources)),
            )
            conn.execute("UPDATE research_threads SET updated_at = now() WHERE id = %s", (thread_id,))

    def list_research_messages(self, thread_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, thread_id, role, content, sources, created_at FROM research_messages "
                "WHERE thread_id = %s ORDER BY id",
                (thread_id,),
            ).fetchall()
        return [{**dict(r), "sources": r["sources"] or []} for r in rows]

    def list_llm_usage_log(
        self, tenant_id: int, limit: int = 50, offset: int = 0, questions_only: bool = False
    ) -> tuple[list[dict], int]:
        where = "tenant_id = %s" + (" AND query_text IS NOT NULL" if questions_only else "")
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM llm_usage_log WHERE {where}", (tenant_id,)).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM llm_usage_log WHERE {where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                (tenant_id, limit, offset),
            ).fetchall()

        entries = []
        for row in rows:
            entry = dict(row)
            entry["retrieved_chunk_ids"] = entry.get("retrieved_chunk_ids") or []
            entry["retrieved_chunk_scores"] = entry.get("retrieved_chunk_scores") or []
            entries.append(entry)
        return entries, int(total)

    def count_llm_usage_since(self, tenant_id: int, since: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM llm_usage_log WHERE tenant_id = %s AND created_at >= %s",
                (tenant_id, since),
            ).fetchone()
        return row["n"]

    # ------------------------------------------------------------------
    # Billing: Plans
    # ------------------------------------------------------------------

    def create_plan(
        self, slug: str, name: str, description: Optional[str] = None, price_cents: int = 0,
        billing_interval: str = "monthly", max_matters: Optional[int] = None,
        max_documents: Optional[int] = None, max_storage_bytes: Optional[int] = None,
        max_llm_calls_per_month: Optional[int] = None, max_owners: Optional[int] = None,
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO plans (slug, name, description, price_cents, billing_interval, "
                "max_matters, max_documents, max_storage_bytes, max_llm_calls_per_month, max_owners, is_active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE) RETURNING *",
                (
                    slug, name, description, price_cents, billing_interval,
                    max_matters, max_documents, max_storage_bytes, max_llm_calls_per_month, max_owners,
                ),
            ).fetchone()
        return dict(row)

    def get_plan(self, plan_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE id = %s", (plan_id,)).fetchone()
        return dict(row) if row else None

    def get_plan_by_slug(self, slug: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE slug = %s", (slug,)).fetchone()
        return dict(row) if row else None

    def list_plans(self, active_only: bool = False) -> list[dict]:
        with self._connect() as conn:
            if active_only:
                rows = conn.execute("SELECT * FROM plans WHERE is_active = TRUE ORDER BY id").fetchall()
            else:
                rows = conn.execute("SELECT * FROM plans ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Billing: Tenant Subscriptions
    # ------------------------------------------------------------------

    def create_tenant_subscription(
        self, tenant_id: int, plan_id: int, status: str, current_period_start: str,
        current_period_end: str, trial_end: Optional[str] = None, provider: Optional[str] = None,
        provider_customer_id: Optional[str] = None, provider_subscription_id: Optional[str] = None,
    ) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO tenant_subscriptions (tenant_id, plan_id, status, current_period_start, "
                "current_period_end, trial_end, provider, provider_customer_id, provider_subscription_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (
                    tenant_id, plan_id, status, current_period_start, current_period_end, trial_end,
                    provider, provider_customer_id, provider_subscription_id,
                ),
            ).fetchone()
        return dict(row)

    def get_subscription_for_tenant(self, tenant_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_subscriptions WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_subscription_status(
        self, tenant_id: int, status: str, canceled_at: Optional[str] = None
    ) -> Optional[dict]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tenant_subscriptions SET status = %s, canceled_at = %s, updated_at = NOW() "
                "WHERE tenant_id = %s",
                (status, canceled_at, tenant_id),
            )
        return self.get_subscription_for_tenant(tenant_id)

    def change_tenant_plan(
        self, tenant_id: int, plan_id: int, current_period_start: str, current_period_end: str
    ) -> Optional[dict]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tenant_subscriptions SET plan_id = %s, current_period_start = %s, "
                "current_period_end = %s, status = 'active', updated_at = NOW() WHERE tenant_id = %s",
                (plan_id, current_period_start, current_period_end, tenant_id),
            )
        return self.get_subscription_for_tenant(tenant_id)

    def get_tenant_resource_usage(self, tenant_id: int) -> dict:
        with self._connect() as conn:
            matters = conn.execute(
                "SELECT COUNT(*) AS n FROM matters WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()["n"]
            documents = conn.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()["n"]
            storage_bytes = conn.execute(
                "SELECT COALESCE(SUM(size), 0) AS n FROM documents WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()["n"]
        # SUM() over an integer column comes back as NUMERIC (a Python
        # Decimal) in Postgres - normalized so both backends return ints.
        return {"matters": int(matters), "documents": int(documents), "storage_bytes": int(storage_bytes)}

    # ------------------------------------------------------------------
    # End-user accounts
    # ------------------------------------------------------------------

    def create_end_user_invite(self, email: str, tenant_id: int, invited_by: Optional[str]) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO end_users (tenant_id, email, status, invited_by) "
                "VALUES (%s, %s, 'invited', %s) RETURNING *",
                (tenant_id, email, invited_by),
            ).fetchone()
        return dict(row)

    def get_end_user(self, end_user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM end_users WHERE id = %s", (end_user_id,)).fetchone()
        return dict(row) if row else None

    def get_end_user_by_email(self, email: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM end_users WHERE email = %s", (email,)).fetchone()
        return dict(row) if row else None

    def list_end_users(self, tenant_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM end_users WHERE tenant_id = %s ORDER BY email", (tenant_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def activate_end_user(self, end_user_id: int, password_hash: str, matter_id: int, activated_at) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE end_users SET password_hash = %s, matter_id = %s, status = 'active', "
                "activated_at = %s, updated_at = NOW() WHERE id = %s RETURNING *",
                (password_hash, matter_id, activated_at, end_user_id),
            ).fetchone()
        return dict(row)

    def update_end_user_password(self, end_user_id: int, password_hash: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE end_users SET password_hash = %s, session_version = session_version + 1, "
                "updated_at = NOW() WHERE id = %s RETURNING *",
                (password_hash, end_user_id),
            ).fetchone()
        return dict(row)

    def set_end_user_status(self, end_user_id: int, status: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE end_users SET status = %s, session_version = session_version + 1, "
                "updated_at = NOW() WHERE id = %s RETURNING *",
                (status, end_user_id),
            ).fetchone()
        return dict(row)

    def create_verification_code(self, email: str, purpose: str, code_hash: str, expires_at) -> dict:
        with self._connect() as conn:
            conn.execute(
                "UPDATE verification_codes SET consumed_at = NOW() "
                "WHERE email = %s AND purpose = %s AND consumed_at IS NULL",
                (email, purpose),
            )
            row = conn.execute(
                "INSERT INTO verification_codes (email, purpose, code_hash, expires_at) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                (email, purpose, code_hash, expires_at),
            ).fetchone()
        return dict(row)

    def get_latest_verification_code(self, email: str, purpose: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM verification_codes WHERE email = %s AND purpose = %s ORDER BY id DESC LIMIT 1",
                (email, purpose),
            ).fetchone()
        return dict(row) if row else None

    def increment_verification_attempts(self, code_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE verification_codes SET attempts = attempts + 1 WHERE id = %s", (code_id,))

    def consume_verification_code(self, code_id: int, consumed_at) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE verification_codes SET consumed_at = %s WHERE id = %s", (consumed_at, code_id))
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
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, path)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL,
    filename TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    extension TEXT,
    size INTEGER,
    sha256 TEXT,
    status TEXT NOT NULL,
    status_detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, relative_path)
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
    tenant_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    created_by TEXT,
    UNIQUE (tenant_id, name, version)
);
CREATE TABLE IF NOT EXISTS matters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE IF NOT EXISTS intake_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id INTEGER NOT NULL,
    thread_id INTEGER,
    title TEXT NOT NULL DEFAULT 'New intake',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploaded_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    matter_id INTEGER,
    original_filename TEXT NOT NULL,
    stored_category TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT,
    processing_status TEXT NOT NULL DEFAULT 'queued',
    status_detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extracted_information (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uploaded_input_id INTEGER NOT NULL REFERENCES uploaded_inputs(id) ON DELETE CASCADE,
    archive_member_filename TEXT,
    content_type TEXT NOT NULL,
    text TEXT NOT NULL,
    provider TEXT NOT NULL,
    is_mock INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    matter_id INTEGER,
    format TEXT NOT NULL,
    stored_category TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    created_at TEXT NOT NULL

);
CREATE TABLE IF NOT EXISTS interview_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL UNIQUE REFERENCES intake_sessions(id) ON DELETE CASCADE,
    language TEXT,
    terms_accepted_at TEXT,
    terms_version TEXT,
    current_state TEXT NOT NULL DEFAULT 'language_selection',
    current_step_index INTEGER NOT NULL DEFAULT 0,
    mandatory_sweep_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS report_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL UNIQUE REFERENCES reports(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending_review',
    reviewed_by TEXT,
    reviewed_at TEXT,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matter_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    matter_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    UNIQUE (owner_id, matter_id)
);

CREATE TABLE IF NOT EXISTS cause_of_action_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    elements TEXT NOT NULL,
    authority_citation TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_session_id INTEGER NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
    matter_id INTEGER NOT NULL,
    format TEXT NOT NULL,
    cause_of_action_ids TEXT NOT NULL,
    stored_category TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    matter_id INTEGER,
    intake_session_id INTEGER,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    query_text TEXT,
    retrieved_chunk_ids TEXT,
    retrieved_chunk_scores TEXT,
    citation_check_result TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    price_cents INTEGER NOT NULL DEFAULT 0,
    billing_interval TEXT NOT NULL DEFAULT 'monthly',
    max_matters INTEGER,
    max_documents INTEGER,
    max_storage_bytes INTEGER,
    max_llm_calls_per_month INTEGER,
    max_owners INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS end_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    status TEXT NOT NULL DEFAULT 'invited',
    matter_id INTEGER,
    session_version INTEGER NOT NULL DEFAULT 0,
    invited_by TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER UNIQUE NOT NULL,
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    status TEXT NOT NULL DEFAULT 'active',
    current_period_start TEXT NOT NULL,
    current_period_end TEXT NOT NULL,
    trial_end TEXT,
    canceled_at TEXT,
    provider TEXT,
    provider_customer_id TEXT,
    provider_subscription_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value) -> str:
    return value if isinstance(value, str) else value.isoformat()


def _add_days(iso_timestamp: str, days: int) -> str:
    from datetime import timedelta

    return (datetime.fromisoformat(iso_timestamp) + timedelta(days=days)).isoformat()


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

    _TENANT_ID_TABLES = (
        "matters", "documents", "folders", "prompt_versions", "cause_of_action_library", "llm_usage_log",
    )

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Every tenant_id column defaults to 1 - this row must
            # always exist so every pre-multi-tenancy caller/test that
            # never heard of tenants keeps resolving to a real tenant.
            conn.execute(
                "INSERT OR IGNORE INTO tenants (id, name, slug, created_at) VALUES (1, 'Default Organization', 'default', ?)",
                (_now(),),
            )
            # CREATE TABLE IF NOT EXISTS never adds a column to a table
            # that already existed before this Step 24 schema change -
            # a real, already-in-use metadata.db predating tenant_id
            # needs it added explicitly, once, here.
            for table in self._TENANT_ID_TABLES:
                existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if "tenant_id" not in existing_columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1")

            # Billing foundation (Phase 5 Step 25): the pre-existing
            # Default Organization (tenant_id=1) is seeded onto a real,
            # explicitly unlimited plan (every limit column NULL) so
            # every Phase 1-4 workflow/test that predates billing keeps
            # working unchanged - it is a real plan+subscription row,
            # not a bypass, and app/billing/service.py treats a NULL
            # limit as "no cap" for any plan, not just this seeded one.
            now = _now()
            conn.execute(
                "INSERT OR IGNORE INTO plans "
                "(id, slug, name, description, price_cents, billing_interval, max_matters, "
                "max_documents, max_storage_bytes, max_llm_calls_per_month, max_owners, is_active, created_at) "
                "VALUES (1, 'default-unlimited', 'Default (Unlimited)', "
                "'Seeded for the pre-existing Default Organization tenant - every limit is unlimited.', "
                "0, 'monthly', NULL, NULL, NULL, NULL, NULL, 1, ?)",
                (now,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO tenant_subscriptions "
                "(id, tenant_id, plan_id, status, current_period_start, current_period_end, created_at, updated_at) "
                "VALUES (1, 1, 1, 'active', ?, ?, ?, ?)",
                (now, _add_days(now, 30), now, now),
            )

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

    def create_folder(self, path: str, tenant_id: int = 1) -> None:
        """Ensure `path` and every ancestor folder has a row."""

        with self._connect() as conn:
            self.create_folder_conn(conn, path, tenant_id)

    def rename_folder(self, old_path: str, new_path: str, tenant_id: int = 1) -> None:
        now = _now()

        with self._connect() as conn:
            self.create_folder_conn(
                conn, new_path.rsplit("/", 1)[0] if "/" in new_path else "", tenant_id
            )

            rows = conn.execute(
                "SELECT path FROM folders WHERE tenant_id = ? AND (path = ? OR path LIKE ?)",
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
                    INSERT INTO folders (tenant_id, path, name, parent_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, path) DO UPDATE SET
                        name = excluded.name,
                        parent_path = excluded.parent_path,
                        updated_at = excluded.updated_at
                    """,
                    (tenant_id, new_folder_path, name, parent_path, now, now),
                )
                conn.execute("DELETE FROM folders WHERE tenant_id = ? AND path = ?", (tenant_id, row["path"]))

            doc_rows = conn.execute(
                "SELECT relative_path, category, filename FROM documents "
                "WHERE tenant_id = ? AND (category = ? OR category LIKE ?)",
                (tenant_id, old_path, f"{old_path}/%"),
            ).fetchall()

            for row in doc_rows:
                new_category = _rewrite_prefix(row["category"], old_path, new_path)
                new_relative_path = _relative_path(new_category, row["filename"])
                conn.execute(
                    """
                    UPDATE documents
                    SET category = ?, relative_path = ?, updated_at = ?
                    WHERE tenant_id = ? AND relative_path = ?
                    """,
                    (new_category, new_relative_path, now, tenant_id, row["relative_path"]),
                )

    def create_folder_conn(self, conn: sqlite3.Connection, path: str, tenant_id: int = 1) -> None:
        if not path:
            return

        now = _now()

        for ancestor in _ancestors(path):
            parent_path = ancestor.rsplit("/", 1)[0] if "/" in ancestor else None
            name = ancestor.rsplit("/", 1)[-1]

            conn.execute(
                """
                INSERT INTO folders (tenant_id, path, name, parent_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, path) DO NOTHING
                """,
                (tenant_id, ancestor, name, parent_path, now, now),
            )

    def delete_folder(self, path: str, tenant_id: int = 1) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM documents WHERE tenant_id = ? AND (category = ? OR category LIKE ?)",
                (tenant_id, path, f"{path}/%"),
            )
            conn.execute(
                "DELETE FROM folders WHERE tenant_id = ? AND (path = ? OR path LIKE ?)",
                (tenant_id, path, f"{path}/%"),
            )

    def list_folders(self, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            folder_rows = conn.execute(
                "SELECT path FROM folders WHERE tenant_id = ? ORDER BY path", (tenant_id,)
            ).fetchall()

            folders = []

            for row in folder_rows:
                path = row["path"]
                count = conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE tenant_id = ? AND (category = ? OR category LIKE ?)",
                    (tenant_id, path, f"{path}/%"),
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
        tenant_id: int = 1,
    ) -> None:
        now = _now()
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            self.create_folder_conn(conn, category, tenant_id)

            conn.execute(
                """
                INSERT INTO documents (
                    tenant_id, category, filename, relative_path, extension, size,
                    sha256, status, status_detail, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, relative_path) DO UPDATE SET
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
                    tenant_id, category, filename, relative_path, extension, size,
                    sha256, status, status_detail, now, now,
                ),
            )

    def delete_document(self, category: str, filename: str, tenant_id: int = 1) -> bool:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE tenant_id = ? AND relative_path = ?", (tenant_id, relative_path)
            )
            return cursor.rowcount > 0

    def get_document(self, category: str, filename: str, tenant_id: int = 1) -> Optional[dict]:
        relative_path = _relative_path(category, filename)

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE tenant_id = ? AND relative_path = ?", (tenant_id, relative_path)
            ).fetchone()

            return dict(row) if row else None

    def list_documents(self, category: Optional[str] = None, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE tenant_id = ? AND (category = ? OR category LIKE ?) "
                    "ORDER BY relative_path",
                    (tenant_id, category, f"{category}/%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE tenant_id = ? ORDER BY relative_path", (tenant_id,)
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
        now = _now()

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE documents
                SET status = ?, status_detail = ?, updated_at = ?
                WHERE tenant_id = ? AND relative_path = ?
                """,
                (status, status_detail, now, tenant_id, relative_path),
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

    def get_matter(self, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM matters WHERE id = ?", (matter_id,)).fetchone()
        return dict(row) if row else None

    def create_matter_assignment(self, owner_id: int, matter_id: int, role: str) -> dict:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO matter_assignments (owner_id, matter_id, role, assigned_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (owner_id, matter_id) DO UPDATE SET role = excluded.role",
                (owner_id, matter_id, role, now),
            )
            row = conn.execute(
                "SELECT * FROM matter_assignments WHERE owner_id = ? AND matter_id = ?", (owner_id, matter_id)
            ).fetchone()
        return dict(row)

    def get_matter_assignment(self, owner_id: int, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM matter_assignments WHERE owner_id = ? AND matter_id = ?", (owner_id, matter_id)
            ).fetchone()
        return dict(row) if row else None

    def list_assignments_for_matter(self, matter_id: int) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM matter_assignments WHERE matter_id = ?", (matter_id,)
                ).fetchall()
            ]
    # ------------------------------------------------------------------
    # Matters
    # ------------------------------------------------------------------

    def get_matter_by_key_hash(self, api_key_hash: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM matters WHERE api_key_hash = ? AND is_active = 1", (api_key_hash,)
            ).fetchone()
            return dict(row) if row else None

    def create_matter(self, name: str, api_key_hash: str, tenant_id: int = 1) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO matters (tenant_id, name, api_key_hash, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
                (tenant_id, name, api_key_hash, now),
            )
            return {
                "id": cursor.lastrowid, "tenant_id": tenant_id, "name": name, "api_key_hash": api_key_hash,
                "is_active": True, "created_at": now,
            }

    def list_matters(self, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM matters WHERE tenant_id = ? ORDER BY name", (tenant_id,)
                ).fetchall()
            ]

    # ------------------------------------------------------------------
    # Prompt Versions
    # ------------------------------------------------------------------

    def get_active_prompt_version(self, name: str, tenant_id: int = 1) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE tenant_id = ? AND name = ? AND is_active = 1",
                (tenant_id, name),
            ).fetchone()
            return dict(row) if row else None

    def list_prompt_versions(self, name: str, tenant_id: int = 1) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE tenant_id = ? AND name = ? ORDER BY version DESC",
                (tenant_id, name),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_prompt_version(
        self, name: str, text: str, created_by: Optional[str] = None, tenant_id: int = 1
    ) -> dict:
        now = _now()
        with self._connect() as conn:
            next_version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE tenant_id = ? AND name = ?",
                (tenant_id, name),
            ).fetchone()[0]

            conn.execute(
                "UPDATE prompt_versions SET is_active = 0 WHERE tenant_id = ? AND name = ?", (tenant_id, name)
            )
            conn.execute(
                "INSERT INTO prompt_versions (tenant_id, name, version, text, is_active, created_at, created_by) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (tenant_id, name, next_version, text, now, created_by),
            )
            return {
                "tenant_id": tenant_id, "name": name, "version": next_version, "text": text, "is_active": True,
                "created_at": now, "created_by": created_by,
            }

    def activate_prompt_version(self, name: str, version: int, tenant_id: int = 1) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE tenant_id = ? AND name = ? AND version = ?",
                (tenant_id, name, version),
            ).fetchone()
            if row is None:
                raise ValueError(f"No such prompt version: {name} v{version}")

            conn.execute(
                "UPDATE prompt_versions SET is_active = 0 WHERE tenant_id = ? AND name = ?", (tenant_id, name)
            )
            conn.execute(
                "UPDATE prompt_versions SET is_active = 1 WHERE tenant_id = ? AND name = ? AND version = ?",
                (tenant_id, name, version),
            )
            return dict(row)

    # ------------------------------------------------------------------
    # Intake Sessions
    # ------------------------------------------------------------------

    def create_intake_session(self, matter_id: int, title: str, thread_id: Optional[int] = None) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO intake_sessions (matter_id, thread_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (matter_id, thread_id, title, now, now),
            )
            return {
                "id": cursor.lastrowid, "matter_id": matter_id, "thread_id": thread_id,
                "title": title, "status": "active", "created_at": now, "updated_at": now,
            }

    def list_intake_sessions(self, matter_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_sessions WHERE matter_id = ? ORDER BY updated_at DESC", (matter_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_intake_session(self, session_id: int, matter_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM intake_sessions WHERE id = ? AND matter_id = ?", (session_id, matter_id)
            ).fetchone()
            return dict(row) if row else None

    def get_intake_session_by_id(self, session_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM intake_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def update_intake_session_status(self, session_id: int, status: str) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE intake_sessions SET status = ?, updated_at = ? WHERE id = ?", (status, now, session_id)
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
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO uploaded_inputs (intake_session_id, matter_id, original_filename, stored_category, "
                "stored_filename, media_type, size, sha256, processing_status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                (intake_session_id, matter_id, original_filename, stored_category, stored_filename, media_type, size, sha256, now, now),
            )
            new_id = cursor.lastrowid
        return self.get_uploaded_input(new_id)

    def get_uploaded_input(self, input_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM uploaded_inputs WHERE id = ?", (input_id,)).fetchone()
            return dict(row) if row else None

    def list_uploaded_inputs(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM uploaded_inputs WHERE intake_session_id = ? ORDER BY id", (intake_session_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def update_uploaded_input_status(
        self, input_id: int, processing_status: str, status_detail: Optional[str] = None
    ) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE uploaded_inputs SET processing_status = ?, status_detail = ?, updated_at = ? WHERE id = ?",
                (processing_status, status_detail, now, input_id),
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
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO extracted_information (
                    uploaded_input_id, archive_member_filename, content_type, text, provider, is_mock, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uploaded_input_id, archive_member_filename, content_type, text, provider, int(is_mock), now),
            )
            return {
                "id": cursor.lastrowid, "uploaded_input_id": uploaded_input_id,
                "archive_member_filename": archive_member_filename, "content_type": content_type,
                "text": text, "provider": provider, "is_mock": is_mock, "created_at": now,
            }

    def list_extracted_information(self, uploaded_input_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM extracted_information WHERE uploaded_input_id = ? ORDER BY id", (uploaded_input_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def add_timeline_event(self, intake_session_id: int, event_type: str, description: str) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO timeline_events (intake_session_id, event_type, description, created_at) VALUES (?, ?, ?, ?)",
                (intake_session_id, event_type, description, now),
            )
            return {
                "id": cursor.lastrowid, "intake_session_id": intake_session_id,
                "event_type": event_type, "description": description, "created_at": now,
            }

    def list_timeline_events(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM timeline_events WHERE intake_session_id = ? ORDER BY id", (intake_session_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def create_report(
        self, intake_session_id: int, matter_id: int, format: str, stored_category: str, stored_filename: str
    ) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO reports (intake_session_id, matter_id, format, stored_category, stored_filename, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (intake_session_id, matter_id, format, stored_category, stored_filename, now),
            )
            new_id = cursor.lastrowid
        return self.get_report(new_id)

    def get_report(self, report_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
            return dict(row) if row else None

    def list_reports(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reports WHERE intake_session_id = ? ORDER BY id", (intake_session_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        # ------------------------------------------------------------------
    # Guided Intake Engine - Interview State
    # ------------------------------------------------------------------
        # ------------------------------------------------------------------
    # Report Review Queue
    # ------------------------------------------------------------------

    def create_report_review(self, report_id: int) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO report_reviews (report_id, status, created_at, updated_at) "
                "VALUES (?, 'pending_review', ?, ?)",
                (report_id, now, now),
            )
            return {
                "id": cursor.lastrowid, "report_id": report_id, "status": "pending_review",
                "reviewed_by": None, "reviewed_at": None, "rejection_reason": None,
                "created_at": now, "updated_at": now,
            }

    def get_report_review(self, report_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM report_reviews WHERE report_id = ?", (report_id,)).fetchone()
            return dict(row) if row else None

    def list_report_reviews(self, status: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM report_reviews WHERE status = ? ORDER BY id", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM report_reviews ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def update_report_review(
        self, report_id: int, status: str, reviewed_by: Optional[str] = None, rejection_reason: Optional[str] = None
    ) -> dict:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE report_reviews
                SET status = ?, reviewed_by = ?, reviewed_at = ?, rejection_reason = ?, updated_at = ?
                WHERE report_id = ?
                """,
                (status, reviewed_by, now, rejection_reason, now, report_id),
            )
            row = conn.execute("SELECT * FROM report_reviews WHERE report_id = ?", (report_id,)).fetchone()
            return dict(row)
    def create_interview_state(self, intake_session_id: int) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO interview_state (
                    intake_session_id, language, terms_accepted_at, terms_version,
                    current_state, current_step_index, mandatory_sweep_completed, created_at, updated_at
                ) VALUES (?, NULL, NULL, NULL, 'language_selection', 0, 0, ?, ?)
                """,
                (intake_session_id, now, now),
            )
            return {
                "id": cursor.lastrowid, "intake_session_id": intake_session_id, "language": None,
                "terms_accepted_at": None, "terms_version": None, "current_state": "language_selection",
                "current_step_index": 0, "mandatory_sweep_completed": False, "created_at": now, "updated_at": now,
            }

    def get_interview_state(self, intake_session_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM interview_state WHERE intake_session_id = ?", (intake_session_id,)
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
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE interview_state
                SET language = ?, current_state = ?, current_step_index = ?,
                    terms_accepted_at = ?, terms_version = ?, mandatory_sweep_completed = ?, updated_at = ?
                WHERE intake_session_id = ?
                """,
                (language, current_state, current_step_index, terms_accepted_at, terms_version,
                 int(mandatory_sweep_completed), now, intake_session_id),
            )
            row = conn.execute(
                "SELECT * FROM interview_state WHERE intake_session_id = ?", (intake_session_id,)
            ).fetchone()
            return dict(row)

    # ------------------------------------------------------------------
    # Guided Intake Engine - Messages
    # ------------------------------------------------------------------

    def add_intake_message(self, intake_session_id: int, role: str, content: str) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO intake_messages (intake_session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (intake_session_id, role, content, now),
            )
            return {
                "id": cursor.lastrowid, "intake_session_id": intake_session_id,
                "role": role, "content": content, "created_at": now,
            }

    def list_intake_messages(self, intake_session_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_messages WHERE intake_session_id = ? ORDER BY id", (intake_session_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Guided Intake Engine - Facts
    # ------------------------------------------------------------------

    def add_intake_fact(self, intake_session_id: int, category: str, fact_key: str, fact_value: str) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO intake_facts (intake_session_id, category, fact_key, fact_value, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (intake_session_id, category, fact_key, fact_value, now),
            )
            return {
                "id": cursor.lastrowid, "intake_session_id": intake_session_id, "category": category,
                "fact_key": fact_key, "fact_value": fact_value, "created_at": now,
            }

    def list_intake_facts(self, intake_session_id: int, category: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM intake_facts WHERE intake_session_id = ? AND category = ? ORDER BY id",
                    (intake_session_id, category),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM intake_facts WHERE intake_session_id = ? ORDER BY id", (intake_session_id,)
                ).fetchall()
            return [dict(row) for row in rows]
        # ------------------------------------------------------------------
    # Cause of Action Library
    # ------------------------------------------------------------------

    def create_cause_of_action(
        self, category: str, name: str, elements: list[str], authority_citation: str, tenant_id: int = 1
    ) -> dict:
        import json

        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO cause_of_action_library (category, name, elements, authority_citation, created_at, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (category, name, json.dumps(elements), authority_citation, now, tenant_id),
            )
            new_id = cursor.lastrowid
        return self.get_cause_of_action(new_id, tenant_id=tenant_id)

    def get_cause_of_action(self, cause_of_action_id: int, tenant_id: int = 1) -> Optional[dict]:
        import json

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cause_of_action_library WHERE id = ? AND tenant_id = ?",
                (cause_of_action_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["elements"] = json.loads(result["elements"])
        return result

    def list_causes_of_action(self, category: Optional[str] = None, tenant_id: int = 1) -> list[dict]:
        import json

        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM cause_of_action_library WHERE category = ? AND tenant_id = ? ORDER BY id",
                    (category, tenant_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cause_of_action_library WHERE tenant_id = ? ORDER BY id", (tenant_id,)
                ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["elements"] = json.loads(item["elements"])
            results.append(item)
        return results

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
        import json

        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO complaints (intake_session_id, matter_id, format, cause_of_action_ids, "
                "stored_category, stored_filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (intake_session_id, matter_id, format, json.dumps(cause_of_action_ids), stored_category, stored_filename, now),
            )
            new_id = cursor.lastrowid
        return self.get_complaint(new_id)

    def get_complaint(self, complaint_id: int) -> Optional[dict]:
        import json

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["cause_of_action_ids"] = json.loads(result["cause_of_action_ids"])
        return result

    def list_complaints(self, intake_session_id: int) -> list[dict]:
        import json

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM complaints WHERE intake_session_id = ? ORDER BY id", (intake_session_id,)
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["cause_of_action_ids"] = json.loads(item["cause_of_action_ids"])
            results.append(item)
        return results

    def add_llm_usage_log(
        self, matter_id, intake_session_id, purpose, model, input_tokens, output_tokens, latency_ms,
        query_text=None, retrieved_chunk_ids=None, retrieved_chunk_scores=None, citation_check_result=None,
        tenant_id: int = 1,
    ) -> dict:
        import json

        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO llm_usage_log (matter_id, intake_session_id, purpose, model, "
                "input_tokens, output_tokens, latency_ms, query_text, retrieved_chunk_ids, "
                "retrieved_chunk_scores, citation_check_result, created_at, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    matter_id, intake_session_id, purpose, model, input_tokens, output_tokens, latency_ms,
                    query_text,
                    json.dumps(retrieved_chunk_ids) if retrieved_chunk_ids is not None else None,
                    json.dumps(retrieved_chunk_scores) if retrieved_chunk_scores is not None else None,
                    citation_check_result, now, tenant_id,
                ),
            )
            new_id = cursor.lastrowid
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM llm_usage_log WHERE id = ?", (new_id,)).fetchone()
        return dict(row)

    def count_llm_usage_since(self, tenant_id: int, since: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM llm_usage_log WHERE tenant_id = ? AND created_at >= ?",
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
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO plans (slug, name, description, price_cents, billing_interval, "
                "max_matters, max_documents, max_storage_bytes, max_llm_calls_per_month, max_owners, "
                "is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    slug, name, description, price_cents, billing_interval,
                    max_matters, max_documents, max_storage_bytes, max_llm_calls_per_month, max_owners, now,
                ),
            )
            new_id = cursor.lastrowid
        return self.get_plan(new_id)

    def get_plan(self, plan_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def get_plan_by_slug(self, slug: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def list_plans(self, active_only: bool = False) -> list[dict]:
        with self._connect() as conn:
            if active_only:
                rows = conn.execute("SELECT * FROM plans WHERE is_active = 1 ORDER BY id").fetchall()
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
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO tenant_subscriptions (tenant_id, plan_id, status, current_period_start, "
                "current_period_end, trial_end, provider, provider_customer_id, provider_subscription_id, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant_id, plan_id, status, current_period_start, current_period_end, trial_end,
                    provider, provider_customer_id, provider_subscription_id, now, now,
                ),
            )
            new_id = cursor.lastrowid
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tenant_subscriptions WHERE id = ?", (new_id,)).fetchone()
        return dict(row)

    def get_subscription_for_tenant(self, tenant_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tenant_subscriptions WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_subscription_status(
        self, tenant_id: int, status: str, canceled_at: Optional[str] = None
    ) -> Optional[dict]:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE tenant_subscriptions SET status = ?, canceled_at = ?, updated_at = ? WHERE tenant_id = ?",
                (status, canceled_at, now, tenant_id),
            )
        return self.get_subscription_for_tenant(tenant_id)

    def change_tenant_plan(
        self, tenant_id: int, plan_id: int, current_period_start: str, current_period_end: str
    ) -> Optional[dict]:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE tenant_subscriptions SET plan_id = ?, current_period_start = ?, "
                "current_period_end = ?, status = 'active', updated_at = ? WHERE tenant_id = ?",
                (plan_id, current_period_start, current_period_end, now, tenant_id),
            )
        return self.get_subscription_for_tenant(tenant_id)

    def get_tenant_resource_usage(self, tenant_id: int) -> dict:
        with self._connect() as conn:
            matters = conn.execute(
                "SELECT COUNT(*) AS n FROM matters WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()["n"]
            documents = conn.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()["n"]
            storage_bytes = conn.execute(
                "SELECT COALESCE(SUM(size), 0) AS n FROM documents WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()["n"]
        return {"matters": matters, "documents": documents, "storage_bytes": storage_bytes}

    # ------------------------------------------------------------------
    # End-user accounts
    # ------------------------------------------------------------------

    def create_end_user_invite(self, email: str, tenant_id: int, invited_by: Optional[str]) -> dict:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO end_users (tenant_id, email, status, invited_by, created_at, updated_at) "
                "VALUES (?, ?, 'invited', ?, ?, ?)",
                (tenant_id, email, invited_by, now, now),
            )
            new_id = cursor.lastrowid
        return self.get_end_user(new_id)

    def get_end_user(self, end_user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM end_users WHERE id = ?", (end_user_id,)).fetchone()
        return dict(row) if row else None

    def get_end_user_by_email(self, email: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM end_users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def list_end_users(self, tenant_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM end_users WHERE tenant_id = ? ORDER BY email", (tenant_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def activate_end_user(self, end_user_id: int, password_hash: str, matter_id: int, activated_at) -> dict:
        with self._connect() as conn:
            conn.execute(
                "UPDATE end_users SET password_hash = ?, matter_id = ?, status = 'active', "
                "activated_at = ?, updated_at = ? WHERE id = ?",
                (password_hash, matter_id, _iso(activated_at), _now(), end_user_id),
            )
        return self.get_end_user(end_user_id)

    def update_end_user_password(self, end_user_id: int, password_hash: str) -> dict:
        with self._connect() as conn:
            conn.execute(
                "UPDATE end_users SET password_hash = ?, session_version = session_version + 1, "
                "updated_at = ? WHERE id = ?",
                (password_hash, _now(), end_user_id),
            )
        return self.get_end_user(end_user_id)

    def set_end_user_status(self, end_user_id: int, status: str) -> dict:
        with self._connect() as conn:
            conn.execute(
                "UPDATE end_users SET status = ?, session_version = session_version + 1, "
                "updated_at = ? WHERE id = ?",
                (status, _now(), end_user_id),
            )
        return self.get_end_user(end_user_id)

    def create_verification_code(self, email: str, purpose: str, code_hash: str, expires_at) -> dict:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE verification_codes SET consumed_at = ? "
                "WHERE email = ? AND purpose = ? AND consumed_at IS NULL",
                (now, email, purpose),
            )
            cursor = conn.execute(
                "INSERT INTO verification_codes (email, purpose, code_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (email, purpose, code_hash, _iso(expires_at), now),
            )
            new_id = cursor.lastrowid
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM verification_codes WHERE id = ?", (new_id,)).fetchone()
        return dict(row)

    def get_latest_verification_code(self, email: str, purpose: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM verification_codes WHERE email = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
                (email, purpose),
            ).fetchone()
        return dict(row) if row else None

    def increment_verification_attempts(self, code_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE verification_codes SET attempts = attempts + 1 WHERE id = ?", (code_id,))

    def consume_verification_code(self, code_id: int, consumed_at) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE verification_codes SET consumed_at = ? WHERE id = ?", (_iso(consumed_at), code_id)
            )
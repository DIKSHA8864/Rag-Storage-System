"""
Shared pytest fixtures.

IMPORTANT: METADATA_BACKEND is forced to "sqlite" here, before
anything else in this file is imported. app/api/storage_api.py builds
its module-level `metadata_repository` at import time via
get_metadata_repository(), which defaults to Postgres (see
config/settings.py and .env) - without this override, merely
importing storage_api during test collection would try to open a real
Postgres connection, making the whole suite depend on Docker/Postgres
being up even though every test isolates its own metadata repository
via monkeypatching anyway. os.environ.setdefault() means a developer
who deliberately wants to run the suite against real Postgres can
still do so by exporting METADATA_BACKEND=postgres before invoking
pytest.

Every endpoint now requires an X-API-Key header (see
app/security/auth.py). Existing endpoint tests exercise business
logic, not authentication, so this autouse fixture bypasses the check
for all of them via FastAPI's dependency_overrides - the same
mechanism the FastAPI docs themselves recommend for testing routes
behind auth. Auth itself is verified separately, without this
override, in tests/test_auth.py.
"""

import os

os.environ.setdefault("METADATA_BACKEND", "sqlite")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-for-production")
import pytest

from app.api import storage_api
from app.security import audit_log
from app.security.auth import require_admin_key, require_end_user_key
from tests.postgres_test_support import ensure_test_database_exists, postgres_reachable


@pytest.fixture(scope="session", autouse=True)
def _ensure_postgres_test_db():
    """
    Contract tests that need a real Postgres (test_metadata_repository.py,
    test_vector_store.py) point at rag_storage_test, a separate database
    from the real one config/settings.py resolves to - see
    tests/postgres_test_support.py for why. Created here once per test
    session (if Postgres is reachable at all) instead of in each of
    those files' own fixtures, so it isn't recreated per test.
    """

    if postgres_reachable():
        ensure_test_database_exists()


@pytest.fixture(autouse=True)
def _bypass_admin_auth():
    """
    Bypasses both auth scopes (require_admin_key and, for
    app/api/end_user_api.py's routes, require_end_user_key) - existing
    endpoint tests exercise business logic, not authentication. Auth
    itself, for both scopes, is verified separately in
    tests/test_auth.py, which clears these overrides.

    require_admin_key resolves to a real-shaped Owner payload (role
    "owner", tenant_id 1 - the seeded Default Organization) rather than
    None, since Step 24's tenant isolation means ordinary business-logic
    endpoints now read owner["tenant_id"] unconditionally, the same way
    they already read owner["role"]/owner["sub"] before this fixture
    existed. Individual tests (e.g. tests/test_matter_workspace.py's
    role-based access tests) still override this further with their own
    dependency_overrides, which take precedence over this default.
    """

    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "1", "email": "test-owner@example.com", "role": "owner", "tenant_id": 1,
    }
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: None
    yield
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


class _FakeJob:
    """
    Minimal stand-in for an rq.job.Job, just enough of its interface
    for app/api/storage_api.py's /process endpoints.
    """

    def __init__(self, job_id: str, func, args: tuple):
        self.id = job_id
        self.result = None
        self.exc_info = None
        self._status = "queued"
        self._func = func
        self._args = args

    def run(self) -> None:
        self._status = "started"
        try:
            self.result = self._func(*self._args)
            self._status = "finished"
        except Exception as exc:  # noqa: BLE001 - mirrors a real job's failure state
            self.exc_info = str(exc)
            self._status = "failed"

    def get_status(self, refresh: bool = True) -> str:
        return self._status


class _FakeQueue:
    """
    Stand-in for an rq.Queue that requires no real Redis: enqueue()
    runs the job synchronously (in-process) instead of handing it to
    a separate worker, since the test suite has no worker process
    running. See tests/test_api.py's processing-status tests for how
    this is used to assert on a finished job's result.
    """

    def __init__(self):
        self._jobs: dict[str, _FakeJob] = {}
        self._next_id = 0

    def enqueue(self, func, *args) -> _FakeJob:
        self._next_id += 1
        job = _FakeJob(f"fake-job-{self._next_id}", func, args)
        self._jobs[job.id] = job
        job.run()
        return job

    def fetch_job(self, job_id: str) -> _FakeJob | None:
        return self._jobs.get(job_id)


@pytest.fixture(autouse=True)
def _fake_job_queue(monkeypatch):
    """
    POST /process enqueues onto a real RQ/Redis queue in production
    (app/jobs/queue.py). The test suite has no Redis/worker running,
    so every test gets a _FakeQueue instead - same enqueue()/
    fetch_job() interface, but it runs the job immediately in-process.
    """

    fake_queue = _FakeQueue()
    monkeypatch.setattr(storage_api, "get_job_queue", lambda: fake_queue)
    return fake_queue


class _FakeVectorStore:
    """
    Stand-in for PgVectorRepository that requires no real Postgres/
    pgvector: an in-memory dict keyed by chunk_id, same
    upsert_chunk_embedding()/similarity_search()/count() interface
    (see app/vector_store/base.py). Real pgvector similarity search is
    covered separately, against a real database, in
    tests/test_vector_store.py.
    """

    def __init__(self):
        self._rows: dict[str, dict] = {}

    def upsert_chunk_embedding(
        self, chunk_id, document_id, category, filename, chunk_text,
        embedding, model_name, metadata=None,
        chapter=None, section=None, start_page=None, end_page=None,
        tenant_id=1,
    ) -> None:
        self._rows[chunk_id] = {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "category": category,
            "filename": filename,
            "chunk_text": chunk_text,
            "embedding": embedding,
            "model_name": model_name,
            "metadata": metadata or {},
            "chapter": chapter,
            "section": section,
            "start_page": start_page,
            "end_page": end_page,
            "tenant_id": tenant_id,
        }

    def similarity_search(self, query_embedding, top_k=5, category=None, tenant_id=1):
        return list(self._rows.values())[:top_k]

    # Same semantics as PgVectorRepository's: library chunks only (never a
    # "matter-<id>" namespace), one tenant, folder prefixes matched literally.
    @staticmethod
    def _is_library(row) -> bool:
        return not row["category"].startswith("matter-")

    @staticmethod
    def _in_folder(row, category) -> bool:
        return row["category"] == category or row["category"].startswith(f"{category}/")

    def _delete_where(self, predicate) -> int:
        doomed = [chunk_id for chunk_id, row in self._rows.items() if self._is_library(row) and predicate(row)]
        for chunk_id in doomed:
            del self._rows[chunk_id]
        return len(doomed)

    def delete_document_chunks(self, category, filename, tenant_id) -> int:
        return self._delete_where(
            lambda r: r["tenant_id"] == tenant_id and r["category"] == category and r["filename"] == filename
        )

    def delete_category_chunks(self, category, tenant_id) -> int:
        return self._delete_where(lambda r: r["tenant_id"] == tenant_id and self._in_folder(r, category))

    def rename_category_chunks(self, old_category, new_category, tenant_id) -> int:
        updated = 0
        for row in self._rows.values():
            if self._is_library(row) and row["tenant_id"] == tenant_id and self._in_folder(row, old_category):
                row["category"] = new_category + row["category"][len(old_category):]
                updated += 1
        return updated

    def chunk_sources(self, chunk_ids, tenant_id) -> dict:
        return {
            chunk_id: {"filename": row["filename"], "category": row["category"]}
            for chunk_id, row in self._rows.items() if chunk_id in set(chunk_ids) and row["tenant_id"] == tenant_id
        }

    def delete_matter_document_chunks(self, matter_id, document_id, tenant_id) -> int:
        doomed = [
            chunk_id for chunk_id, row in self._rows.items()
            if row["tenant_id"] == tenant_id and row["category"] == f"matter-{matter_id}" and row["document_id"] == document_id
        ]
        for chunk_id in doomed:
            del self._rows[chunk_id]
        return len(doomed)

    def delete_library_chunks_except(self, keep_chunk_ids) -> int:
        return self._delete_where(lambda r: r["chunk_id"] not in keep_chunk_ids)

    def count(self) -> int:
        return len(self._rows)


@pytest.fixture(autouse=True)
def _fake_vector_store(monkeypatch):
    """
    POST /process writes each chunk's embedding to a real pgvector
    table in production (app/vector_store/vector_repository.py). The
    test suite has no Postgres/pgvector guaranteed reachable at
    collection time, so every test gets a _FakeVectorStore instead.
    """

    fake_store = _FakeVectorStore()
    monkeypatch.setattr(storage_api, "get_vector_store", lambda: fake_store)
    return fake_store


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path, monkeypatch):
    """
    Any endpoint test that triggers an upload/delete/rename/etc.
    writes an audit entry. Without this, tests that don't explicitly
    redirect it (anything other than test_audit_log.py) would append
    to the real project's logs/audit.log as a side effect.
    """

    monkeypatch.setattr(
        audit_log.get_settings(), "audit_log_path", str(tmp_path / "audit.log")
    )

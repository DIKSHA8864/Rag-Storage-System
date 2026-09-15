"""
Shared Postgres *test* database helpers.

tests/test_metadata_repository.py and tests/test_vector_store.py both
run contract tests against a real Postgres - and both TRUNCATE tables
to isolate one test from the next. They must never point at
config/settings.py's real POSTGRES_DB (rag_storage) - the same
database the app itself, and a developer's own `docker compose up -d`,
uses - or running pytest wipes real documents/chunk_embeddings.

TEST_DSN points at a separate database instead: rag_storage_test, on
the same docker-compose Postgres server (same host/port/credentials -
nothing new to run). ensure_test_database_exists() creates it on first
use if it doesn't exist yet - it won't already exist for anyone who
set up docker-compose.yml before this file existed, and a fresh
`docker compose up -d` volume only runs init scripts once, so this
can't be handled by an init script for an already-initialized volume
either. Being a genuinely separate database (not just a separate
schema) means a TRUNCATE or a stray migration can never reach real
data even via a coding mistake - there's no real data in
rag_storage_test's tables to reach.
"""

import psycopg

_HOST_DSN = "postgresql://raguser:ragpassword@localhost:5432"
MAINTENANCE_DSN = f"{_HOST_DSN}/postgres"
TEST_DSN = f"{_HOST_DSN}/rag_storage_test"


def postgres_reachable() -> bool:
    try:
        with psycopg.connect(MAINTENANCE_DSN, connect_timeout=2):
            return True
    except Exception:
        return False


def ensure_test_database_exists() -> None:
    """Create rag_storage_test on the docker-compose Postgres server if it doesn't exist yet."""

    with psycopg.connect(MAINTENANCE_DSN, connect_timeout=2, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'rag_storage_test'"
        ).fetchone()

        if not exists:
            conn.execute("CREATE DATABASE rag_storage_test")

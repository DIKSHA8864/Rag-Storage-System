"""
pgvector-backed vector store - the default (and, today, only)
VectorStore implementation. See app/vector_store/base.py for the
interface this implements.

Reuses the same Postgres instance app/metadata/postgres_repository.py
talks to (config/settings.py's postgres_dsn) - pgvector is a Postgres
extension, not a separate service, so no new database is needed. See
database/migrations/0002_pgvector.sql for the enabled extension and
the chunk_embeddings table.

Also exposes keyword_search() - not part of the VectorStore interface
(a hypothetical future non-Postgres backend, e.g. Chroma, wouldn't
necessarily support full-text search the same way), but a concrete
extra method callers that already know they're talking to Postgres
can use directly. app/retrieval/search.py does exactly that, running
it alongside similarity_search() for hybrid retrieval.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.vector_store.base import VectorStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"


class PgVectorRepository(VectorStore):

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """
        Idempotent (every statement is IF NOT EXISTS), same as
        PostgresMetadataRepository._apply_migrations() - safe to run
        again even if the metadata repository already applied these
        same files.
        """

        with self._connect() as conn:
            for migration_path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
                conn.execute(migration_path.read_text(encoding="utf-8"))

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            register_vector(conn)
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    def upsert_chunk_embedding(
        self,
        chunk_id: str,
        document_id: str,
        category: str,
        filename: str,
        chunk_text: str,
        embedding: list[float],
        model_name: str,
        metadata: Optional[dict] = None,
        chapter: Optional[str] = None,
        section: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
        tenant_id: int = 1,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chunk_embeddings (
                    chunk_id, document_id, category, filename,
                    chunk_text, embedding, model_name, metadata,
                    chapter, section, start_page, end_page, tenant_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    category = excluded.category,
                    filename = excluded.filename,
                    chunk_text = excluded.chunk_text,
                    embedding = excluded.embedding,
                    model_name = excluded.model_name,
                    metadata = excluded.metadata,
                    chapter = excluded.chapter,
                    section = excluded.section,
                    start_page = excluded.start_page,
                    end_page = excluded.end_page,
                    tenant_id = excluded.tenant_id,
                    updated_at = now()
                """,
                (
                    chunk_id,
                    document_id,
                    category,
                    filename,
                    chunk_text,
                    Vector(embedding),
                    model_name,
                    Jsonb(metadata or {}),
                    chapter,
                    section,
                    start_page,
                    end_page,
                    tenant_id,
                ),
            )

    def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        category: Optional[str] = None,
        tenant_id: int = 1,
    ) -> list[dict]:
        # pgvector's <=> operator is cosine *distance* (0 = identical,
        # 2 = opposite) - converting to similarity (1 = identical, -1 =
        # opposite) keeps the score comparable to keyword_search()'s
        # ts_rank and easier to reason about ("higher is better",
        # everywhere) once app/retrieval/ combines the two.
        #
        # Wrapped in pgvector.Vector explicitly (rather than passed as
        # a plain list) so psycopg adapts it unambiguously to the
        # `vector` type - a bare list/array parameter next to the
        # `<=>` operator resolves to `double precision[]` instead,
        # which has no matching operator overload.
        query_vector = Vector(query_embedding)

        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    """
                    SELECT chunk_id, document_id, category, filename, chunk_text, chapter, section, start_page, end_page, metadata,
                           1 - (embedding <=> %s) AS score
                    FROM chunk_embeddings
                    WHERE tenant_id = %s AND (category = %s OR category LIKE %s)
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (query_vector, tenant_id, category, f"{category}/%", query_vector, top_k),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT chunk_id, document_id, category, filename, chunk_text, chapter, section, start_page, end_page, metadata,
                           1 - (embedding <=> %s) AS score
                    FROM chunk_embeddings
                    WHERE tenant_id = %s AND category NOT LIKE 'matter-%%'
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (query_vector, tenant_id, query_vector, top_k),
                ).fetchall()

            return [dict(row) for row in rows]

    # Library chunks only: a Matter's namespace is category "matter-<id>"
    # (app/matter_rag/) - the same predicate library search uses.
    # Folder prefixes use starts_with(), not LIKE: "_" in a folder name
    # (e.g. "Employment_law") is a LIKE wildcard.
    _LIBRARY_ONLY = "category NOT LIKE 'matter-%%'"

    def delete_document_chunks(self, category: str, filename: str, tenant_id: int) -> int:
        with self._connect() as conn:
            return conn.execute(
                f"""
                DELETE FROM chunk_embeddings
                WHERE tenant_id = %s AND category = %s AND filename = %s AND {self._LIBRARY_ONLY}
                """,
                (tenant_id, category, filename),
            ).rowcount

    def chunk_sources(self, chunk_ids: list[str], tenant_id: int) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_id, filename, category FROM chunk_embeddings WHERE tenant_id = %s AND chunk_id = ANY(%s)",
                (tenant_id, list(chunk_ids)),
            ).fetchall()
        return {row["chunk_id"]: {"filename": row["filename"], "category": row["category"]} for row in rows}

    def delete_matter_document_chunks(self, matter_id: int, document_id: str, tenant_id: int) -> int:
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM chunk_embeddings WHERE tenant_id = %s AND category = %s AND document_id = %s",
                (tenant_id, f"matter-{matter_id}", document_id),
            ).rowcount

    def delete_category_chunks(self, category: str, tenant_id: int) -> int:
        with self._connect() as conn:
            return conn.execute(
                f"""
                DELETE FROM chunk_embeddings
                WHERE tenant_id = %s AND (category = %s OR starts_with(category, %s)) AND {self._LIBRARY_ONLY}
                """,
                (tenant_id, category, f"{category}/"),
            ).rowcount

    def rename_category_chunks(self, old_category: str, new_category: str, tenant_id: int) -> int:
        with self._connect() as conn:
            return conn.execute(
                f"""
                UPDATE chunk_embeddings
                SET category = %s || substr(category, length(%s) + 1), updated_at = now()
                WHERE tenant_id = %s AND (category = %s OR starts_with(category, %s)) AND {self._LIBRARY_ONLY}
                """,
                (new_category, old_category, tenant_id, old_category, f"{old_category}/"),
            ).rowcount

    def delete_library_chunks_except(self, keep_chunk_ids: set[str]) -> int:
        with self._connect() as conn:
            return conn.execute(
                f"""
                DELETE FROM chunk_embeddings
                WHERE {self._LIBRARY_ONLY} AND NOT (chunk_id = ANY(%s))
                """,
                (list(keep_chunk_ids),),
            ).rowcount

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM chunk_embeddings").fetchone()
            return row["count"]

    # ------------------------------------------------------------------
    # Postgres-specific extras (not part of the VectorStore interface)
    # ------------------------------------------------------------------

    def keyword_search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        tenant_id: int = 1,
    ) -> list[dict]:
        """
        Full-text keyword search over chunk_text using Postgres's
        built-in text search (ts_rank against a websearch_to_tsquery)
        - the "basic keyword match" half of hybrid retrieval, run
        alongside similarity_search() rather than instead of it. See
        app/retrieval/search.py.

        `query`'s words are OR'd together (via websearch_to_tsquery,
        not the default AND plainto_tsquery would use) - retrieval
        queries are usually a full natural-language question ("how
        long does X take"), and requiring every single word to appear
        in a chunk would return nothing for most of them. A chunk
        matching more of the query's words still ranks higher via
        ts_rank, so this is strictly looser, not lower quality.

        `tenant_id` filtering is unconditional, same as
        similarity_search() - never a cross-tenant leak surface.
        """

        or_query = " or ".join(query.split()) or query

        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    """
                    SELECT chunk_id, document_id, category, filename, chunk_text, chapter, section, start_page, end_page, metadata,
                           ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', %s)) AS score
                    FROM chunk_embeddings
                    WHERE tenant_id = %s AND (category = %s OR category LIKE %s)
                      AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', %s)
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (or_query, tenant_id, category, f"{category}/%", or_query, top_k),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT chunk_id, document_id, category, filename, chunk_text, chapter, section, start_page, end_page, metadata,
                           ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', %s)) AS score
                    FROM chunk_embeddings
                    WHERE tenant_id = %s AND category NOT LIKE 'matter-%%'
                      AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', %s)
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (or_query, tenant_id, or_query, top_k),
                ).fetchall()

            return [dict(row) for row in rows]

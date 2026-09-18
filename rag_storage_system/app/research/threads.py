"""
Persisted research threads (Blueprint Phase 2: "Threads persisted; any
thread or answer exports via the document service").

An answer's source list is stored WITH the message, not recomputed on
read: the console's source panel and any exported memo must show what
was actually cited when the answer was written, even after the library
has been re-indexed since.

Raw psycopg, same shape as app/security/owner_repository.py.
"""

import json
from typing import Optional

from psycopg import connect

from config.settings import get_settings


def get_connection():
    settings = get_settings()
    return connect(settings.postgres_dsn)


def create_thread(owner_id: int, title: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_threads (owner_id, title)
                VALUES (%s, %s)
                RETURNING id, owner_id, title, created_at, updated_at
                """,
                (owner_id, title[:200]),
            )
            row = cur.fetchone()
        conn.commit()

    return _thread_row(row)


def list_threads(owner_id: int, limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.owner_id, t.title, t.created_at, t.updated_at,
                       COUNT(m.id) FILTER (WHERE m.role = 'question')
                FROM research_threads t
                LEFT JOIN research_messages m ON m.thread_id = t.id
                WHERE t.owner_id = %s
                GROUP BY t.id
                ORDER BY t.updated_at DESC
                LIMIT %s
                """,
                (owner_id, limit),
            )
            rows = cur.fetchall()

    return [{**_thread_row(row), "question_count": row[5]} for row in rows]


def get_thread(thread_id: int, owner_id: int) -> Optional[dict]:
    """
    One thread with all its messages, or None if it doesn't exist or
    belongs to someone else. owner_id is part of the WHERE clause, not
    an afterthought check - the same discipline Phase 4's matter
    isolation will need.
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, owner_id, title, created_at, updated_at
                FROM research_threads
                WHERE id = %s AND owner_id = %s
                """,
                (thread_id, owner_id),
            )
            thread_row = cur.fetchone()

            if thread_row is None:
                return None

            cur.execute(
                """
                SELECT id, role, content, sources, citation_status,
                       citation_detail, created_at
                FROM research_messages
                WHERE thread_id = %s
                ORDER BY id
                """,
                (thread_id,),
            )
            message_rows = cur.fetchall()

    return {
        **_thread_row(thread_row),
        "messages": [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "sources": row[3] or [],
                "citation_status": row[4],
                "citation_detail": row[5] or {},
                "created_at": row[6],
            }
            for row in message_rows
        ],
    }


def append_exchange(thread_id: int, question: str, answer: str,
                    sources: list[dict], citation_status: str,
                    citation_detail: dict) -> None:
    """Store one question + its answer, and bump the thread's updated_at."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_messages (thread_id, role, content)
                VALUES (%s, 'question', %s)
                """,
                (thread_id, question),
            )
            cur.execute(
                """
                INSERT INTO research_messages
                    (thread_id, role, content, sources, citation_status, citation_detail)
                VALUES (%s, 'answer', %s, %s, %s, %s)
                """,
                (
                    thread_id,
                    answer,
                    json.dumps(sources),
                    citation_status,
                    json.dumps(citation_detail),
                ),
            )
            cur.execute(
                "UPDATE research_threads SET updated_at = NOW() WHERE id = %s",
                (thread_id,),
            )
        conn.commit()


def delete_thread(thread_id: int, owner_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM research_threads WHERE id = %s AND owner_id = %s",
                (thread_id, owner_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()

    return deleted


def _thread_row(row) -> dict:
    return {
        "id": row[0],
        "owner_id": row[1],
        "title": row[2],
        "created_at": row[3],
        "updated_at": row[4],
    }
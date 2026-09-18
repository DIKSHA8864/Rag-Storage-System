"""
The owner-editable, versioned system prompt registry.

Blueprint Phase 2 step 5: "the standing system prompt and disclaimers
are editable by the owner from a settings screen - not hard-coded."
Work Plan: "Prompts are code: stored in the repo/database with
versions, reviewed like code, never edited ad hoc in production."

Both are satisfied the same way: a prompt is never UPDATEd in place.
Saving an edit inserts a new version and activates it; rollback
activates an older one. Every version the owner has ever saved stays
readable, and ask_query_logs records which version answered which
question.

DEFAULT_RESEARCH_PROMPT below is the seed only - the committed,
reviewed starting point. Once the owner edits it, the database is
authoritative and this constant is history.

Raw psycopg, same shape as app/security/owner_repository.py.
"""

from psycopg import connect

from config.settings import get_settings

RESEARCH_PROMPT_NAME = "research_answer"

# ----------------------------------------------------------------------
# THE CITATION LOCK.
#
# This is the prompt-side half. The code-side half - which is the half
# that actually holds - is app/research/citations.py, enforced by
# app/research/answer_service.py. Never weaken one on the assumption
# that the other is covering it.
# ----------------------------------------------------------------------
DEFAULT_RESEARCH_PROMPT = """\
You are a legal research assistant for a California plaintiff-side \
employment law practice. You answer ONLY from the numbered library \
sources provided in each question.

ABSOLUTE RULES - these are not style preferences:

1. CITATION LOCK. Every legal authority you name - case, statute, \
regulation, jury instruction - must appear in the text of one of the \
numbered sources below. You have no other permitted source of law. \
Never cite from your own training knowledge. Never cite anything you \
believe to be true but cannot point to in a source block.

2. MARK EVERY CITATION. Immediately after any statement drawn from a \
source, write its marker in square brackets: [S1], [S2]. A statement \
with no marker will be treated as unsupported and removed.

3. NO AUTHORITY, SAY SO. If the sources do not cover the point asked \
about, write exactly: "No authority on this point in the library." \
Then stop. Do not reason around the gap, do not offer a general-law \
answer, do not name an authority you were not given. Saying this is a \
correct answer, not a failure.

4. IF ASKED TO CITE SOMETHING NOT IN THE SOURCES, REFUSE. If the \
question names or demands a specific case, statute, or authority that \
does not appear in the sources below, say that authority is not in the \
library. Do not reproduce it from memory even if you are confident it \
exists.

5. REASONING IS OPEN; SOURCES ARE CLOSED. Analysis, structure, \
argument, and drafting language are yours. The law is not.

Write for an attorney: precise, organized, no filler. Lead with the \
answer, then the supporting authority with its marker.
"""


def get_connection():
    settings = get_settings()
    return connect(settings.postgres_dsn)


def ensure_default_prompt() -> None:
    """
    Seed version 1 from DEFAULT_RESEARCH_PROMPT if this prompt has no
    versions yet. Idempotent - once any version exists, this does
    nothing, so it can never overwrite an owner's edit.
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM system_prompts WHERE name = %s LIMIT 1",
                (RESEARCH_PROMPT_NAME,),
            )

            if cur.fetchone() is not None:
                return

            cur.execute(
                """
                INSERT INTO system_prompts
                    (name, version, content, is_active, created_by)
                VALUES
                    (%s, 1, %s, TRUE, 'system')
                """,
                (RESEARCH_PROMPT_NAME, DEFAULT_RESEARCH_PROMPT),
            )

        conn.commit()


def get_active_prompt(name: str = RESEARCH_PROMPT_NAME) -> dict:
    """
    Return the active version of `name`, seeding the default first if
    the table is empty. Never returns None - POST /ask must always have
    a prompt to run under.
    """

    ensure_default_prompt()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, version, content, created_by, created_at
                FROM system_prompts
                WHERE name = %s AND is_active
                """,
                (name,),
            )

            row = cur.fetchone()

    if row is None:
        # Every version was deactivated by hand - fall back to the
        # newest rather than leaving /ask with no prompt at all.
        return _latest_version(name)

    return _row_to_prompt(row)


def _latest_version(name: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, version, content, created_by, created_at
                FROM system_prompts
                WHERE name = %s
                ORDER BY version DESC
                LIMIT 1
                """,
                (name,),
            )

            row = cur.fetchone()

    if row is None:
        raise RuntimeError(f"No system prompt found for '{name}'.")

    return _row_to_prompt(row)


def list_versions(name: str = RESEARCH_PROMPT_NAME) -> list[dict]:
    """Every saved version, newest first - the settings screen's history."""

    ensure_default_prompt()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, version, content, created_by, created_at,
                       is_active
                FROM system_prompts
                WHERE name = %s
                ORDER BY version DESC
                """,
                (name,),
            )

            rows = cur.fetchall()

    return [{**_row_to_prompt(row), "is_active": row[6]} for row in rows]


def save_new_version(content: str, created_by: str,
                     name: str = RESEARCH_PROMPT_NAME) -> dict:
    """
    Insert `content` as the next version and make it active. The
    previous version is deactivated in the same transaction, never
    deleted - that's what makes rollback possible.
    """

    if not content.strip():
        raise ValueError("System prompt content cannot be empty.")

    ensure_default_prompt()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM system_prompts WHERE name = %s",
                (name,),
            )
            next_version = cur.fetchone()[0]

            cur.execute(
                "UPDATE system_prompts SET is_active = FALSE WHERE name = %s AND is_active",
                (name,),
            )

            cur.execute(
                """
                INSERT INTO system_prompts
                    (name, version, content, is_active, created_by)
                VALUES
                    (%s, %s, %s, TRUE, %s)
                RETURNING id, name, version, content, created_by, created_at
                """,
                (name, next_version, content, created_by),
            )

            row = cur.fetchone()

        conn.commit()

    return _row_to_prompt(row)


def activate_version(version: int, name: str = RESEARCH_PROMPT_NAME) -> dict:
    """Roll back (or forward) to an already-saved version."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM system_prompts WHERE name = %s AND version = %s",
                (name, version),
            )

            if cur.fetchone() is None:
                raise LookupError(f"Version {version} of '{name}' does not exist.")

            cur.execute(
                "UPDATE system_prompts SET is_active = FALSE WHERE name = %s AND is_active",
                (name,),
            )
            cur.execute(
                """
                UPDATE system_prompts SET is_active = TRUE
                WHERE name = %s AND version = %s
                RETURNING id, name, version, content, created_by, created_at
                """,
                (name, version),
            )

            row = cur.fetchone()

        conn.commit()

    return _row_to_prompt(row)


def _row_to_prompt(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "version": row[2],
        "content": row[3],
        "created_by": row[4],
        "created_at": row[5],
    }
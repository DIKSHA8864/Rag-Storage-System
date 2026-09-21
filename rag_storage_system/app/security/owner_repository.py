from config.settings import get_settings


def get_connection():
    # Deferred import - see app/metadata/__init__.py's get_metadata_repository()
    # for the same reasoning: importing this module (and everything that
    # imports it, e.g. app/api/auth_api.py -> app/api/storage_api.py ->
    # tests/conftest.py) must not require psycopg to successfully load
    # unless a real Postgres connection is actually attempted here.
    from psycopg import connect

    settings = get_settings()
    return connect(settings.postgres_dsn)


def create_owner_table() -> None:
    """Create the owners table if it does not already exist."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS owners (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role VARCHAR(50) NOT NULL DEFAULT 'owner',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

        conn.commit()


def get_owner_by_email(email: str):
    """Return an owner record by email."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    email,
                    password_hash,
                    role,
                    is_active,
                    created_at
                FROM owners
                WHERE LOWER(email) = LOWER(%s)
                """,
                (email,),
            )

            row = cur.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "email": row[1],
        "password_hash": row[2],
        "role": row[3],
        "is_active": row[4],
        "created_at": row[5],
    }


def create_owner(email: str, password_hash: str):
    """Create the initial Owner account."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO owners
                    (email, password_hash, role, is_active)
                VALUES
                    (%s, %s, 'owner', TRUE)
                RETURNING id, email, role, is_active, created_at
                """,
                (email.lower().strip(), password_hash),
            )

            row = cur.fetchone()

        conn.commit()

    return {
        "id": row[0],
        "email": row[1],
        "role": row[2],
        "is_active": row[3],
        "created_at": row[4],
    }
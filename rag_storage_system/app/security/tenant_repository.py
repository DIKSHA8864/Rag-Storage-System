"""
Tenant (firm/organization) accounts. Same connection pattern as
app/security/owner_repository.py - every owner belongs to exactly one
tenant (owners.tenant_id); every tenant-owned resource (matters,
documents, folders, prompt versions, the cause-of-action library, and
usage logs) carries a tenant_id that must match the caller's own
before it's ever returned - see app/security/auth.py's
ensure_matter_access() and the tenant_id-aware repository methods in
app/metadata/.
"""

from config.settings import get_settings


def get_connection():
    # Deferred import - see owner_repository.py's get_connection() for
    # the same reasoning: importing this module must not require
    # psycopg to successfully load unless a real Postgres connection is
    # actually attempted here.
    from psycopg import connect

    settings = get_settings()
    return connect(settings.postgres_dsn)


def create_tenant_table() -> None:
    """Create the tenants table (and the seeded Default Organization) if it does not already exist."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(100) UNIQUE NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (1, 'Default Organization', 'default') "
                "ON CONFLICT (id) DO NOTHING"
            )

        conn.commit()


def create_tenant(name: str, slug: str) -> dict:
    """Create a new tenant (firm/organization)."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tenants (name, slug)
                VALUES (%s, %s)
                RETURNING id, name, slug, is_active, created_at
                """,
                (name.strip(), slug.strip().lower()),
            )

            row = cur.fetchone()

        conn.commit()

    return {
        "id": row[0],
        "name": row[1],
        "slug": row[2],
        "is_active": row[3],
        "created_at": row[4],
    }


def get_tenant_by_id(tenant_id: int):
    """Return a tenant record by id, or None."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, is_active, created_at FROM tenants WHERE id = %s",
                (tenant_id,),
            )

            row = cur.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "slug": row[2],
        "is_active": row[3],
        "created_at": row[4],
    }


def get_tenant_by_slug(slug: str):
    """Return a tenant record by slug, or None."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, is_active, created_at FROM tenants WHERE LOWER(slug) = LOWER(%s)",
                (slug,),
            )

            row = cur.fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "slug": row[2],
        "is_active": row[3],
        "created_at": row[4],
    }


def list_tenants() -> list:
    """Return every tenant, for Owner-level administration."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, slug, is_active, created_at FROM tenants ORDER BY id")

            rows = cur.fetchall()

    return [
        {"id": row[0], "name": row[1], "slug": row[2], "is_active": row[3], "created_at": row[4]}
        for row in rows
    ]

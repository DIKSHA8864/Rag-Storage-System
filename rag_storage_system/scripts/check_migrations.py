"""
Dry-run every database migration against the configured Postgres
database and report the first one that fails - which file, which line,
and the current columns of the tables that line touches. Everything is
rolled back at the end: this never changes the database.

Usage:
    python scripts/check_migrations.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402

from config.settings import get_settings  # noqa: E402

MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"


def _statements(sql: str) -> list[str]:
    """Split on ';' outside quotes, dollar-quoted bodies ($$ / $fn$) and -- comments."""

    statements, current, i, quote = [], [], 0, None
    while i < len(sql):
        if quote is None and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
            continue
        tag = re.match(r"\$[A-Za-z_]*\$", sql[i:])
        if tag and quote in (None, tag.group(0)):
            quote = None if quote == tag.group(0) else tag.group(0)
            current.append(tag.group(0))
            i += len(tag.group(0))
            continue
        char = sql[i]
        if char == "'" and quote in (None, "'"):
            quote = None if quote == "'" else "'"
        if char == ";" and quote is None:
            if "".join(current).strip():
                statements.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    if "".join(current).strip():
        statements.append("".join(current).strip())
    return statements


def _columns(conn, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position", (table,)
    ).fetchall()
    return [row[0] for row in rows]


def main() -> int:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    print(f"{len(files)} migration files in {MIGRATIONS_DIR}:")
    print("  " + ", ".join(f.name for f in files))

    settings = get_settings()
    print(f"Database: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}\n")
    with psycopg.connect(settings.postgres_dsn) as conn:
        failures = 0
        try:
            for path in files:
                sql = path.read_text(encoding="utf-8")
                for statement in _statements(sql):
                    conn.execute("SAVEPOINT migration")
                    try:
                        conn.execute(statement)
                    except psycopg.Error as exc:
                        conn.execute("ROLLBACK TO SAVEPOINT migration")
                        print(f"FAILED: {path.name}")
                        print(f"  error: {str(exc).strip()}")
                        print("  statement: " + " ".join(statement.split())[:300])
                        tables = set(re.findall(r"(?:\bON|TABLE(?: IF NOT EXISTS)?|INTO|FROM|JOIN)\s+([a-z_]+)", statement, re.I))
                        for table in sorted(tables - {"if", "only"}):
                            print(f"  table {table} columns now: {_columns(conn, table) or '(table does not exist)'}")
                        failures += 1
                        break
                else:
                    print(f"ok      {path.name}")
            if failures:
                print(f"\n{failures} migration file(s) failed - nothing was changed.")
                return 1
            print("\nAll migrations apply cleanly.")
            return 0
        finally:
            conn.rollback()  # dry run - nothing is kept


if __name__ == "__main__":
    raise SystemExit(main())

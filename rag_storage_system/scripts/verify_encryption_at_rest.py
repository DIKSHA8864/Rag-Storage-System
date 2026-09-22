"""
Encryption-at-rest is a hosting/infra property (disk/volume
encryption on the managed Postgres instance, e.g. AWS RDS "Encrypted"
= true, or the hosting provider's equivalent) - this script cannot
see that from inside the app. What it CAN verify: the Postgres
connection itself is using SSL/TLS, which is what you'd expect to
also be true wherever encryption-at-rest is properly configured.

Run: python scripts/verify_encryption_at_rest.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_settings  # noqa: E402


def main() -> None:
    import psycopg

    settings = get_settings()

    with psycopg.connect(settings.postgres_dsn) as conn:
        row = conn.execute("SHOW ssl").fetchone()
        ssl_on = row[0] == "on"

        print("=" * 60)
        print("ENCRYPTION-AT-REST VERIFICATION")
        print("=" * 60)
        print(f"Postgres connection SSL: {'ON' if ssl_on else 'OFF'}")

        if not ssl_on:
            print("WARNING: connection is not using SSL. This does not by")
            print("itself mean data-at-rest is unencrypted, but confirm")
            print("separately with your hosting provider's console:")
            print("  - AWS RDS: Database > Configuration > 'Encrypted' = true")
            print("  - Supabase: Project Settings > Database > confirm disk encryption (on by default)")
            print("  - Self-hosted: confirm the underlying volume/disk uses LUKS or equivalent")

    print("=" * 60)


if __name__ == "__main__":
    main()
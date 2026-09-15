"""
Create the Owner account used to log in via POST /auth/login.

Creates the `owners` table if it doesn't exist yet (see
app/security/owner_repository.py:create_owner_table) and inserts one
Owner row with an Argon2-hashed password (app/security/auth.py).

Usage:
    python scripts/create_owner.py <email> <password>
    python scripts/create_owner.py                      (prompts for both)
"""

import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from psycopg.errors import UniqueViolation  # noqa: E402

from app.security.auth import hash_password  # noqa: E402
from app.security.owner_repository import create_owner, create_owner_table  # noqa: E402


def main() -> int:
    if len(sys.argv) == 3:
        email, password = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 1:
        email = input("Owner email: ").strip()
        password = getpass.getpass("Owner password: ")
    else:
        print("Usage: python scripts/create_owner.py [<email> <password>]")
        return 1

    if not email or not password:
        print("Email and password are both required.")
        return 1

    create_owner_table()

    try:
        owner = create_owner(email, hash_password(password))
    except UniqueViolation:
        print(f"An owner with email '{email}' already exists.")
        return 1

    print(f"Owner created: id={owner['id']} email={owner['email']} role={owner['role']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

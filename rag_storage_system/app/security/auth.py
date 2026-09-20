"""
Authentication and authorization.

Owner/Admin:
    Email + password -> JWT access token -> Authorization: Bearer <token>

End User:
    Separate X-End-User-Key authentication remains unchanged for now.

The existing `require_admin_key` dependency name is intentionally kept
so storage_api.py does not need to change every protected endpoint.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from config.settings import get_settings


# ----------------------------------------------------------------------
# Password hashing
# ----------------------------------------------------------------------

password_hash = PasswordHash.recommended()


# ----------------------------------------------------------------------
# HTTP authentication
# ----------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


# ----------------------------------------------------------------------
# Password helpers
# ----------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2."""

    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its stored hash."""

    return password_hash.verify(password, hashed_password)


# ----------------------------------------------------------------------
# JWT helpers
# ----------------------------------------------------------------------

def create_access_token(owner_id: int, email: str) -> str:
    """Create a signed JWT access token for the Owner."""

    settings = get_settings()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    payload = {
        "sub": str(owner_id),
        "email": email,
        "role": "owner",
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""

    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired.",
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    if payload.get("role") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required.",
        )

    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    return payload


# ----------------------------------------------------------------------
# Admin/Owner dependency
# ----------------------------------------------------------------------

def require_admin_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        _bearer_scheme
    ),
) -> dict:
    """
    FastAPI dependency for protected Owner/Admin endpoints.

    The function name is kept as `require_admin_key` so existing
    storage_api.py endpoints do not need to be rewritten.

    Authentication is now:

        Authorization: Bearer <JWT>
    """

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return decode_access_token(credentials.credentials)


# ----------------------------------------------------------------------
# End User authentication
# ----------------------------------------------------------------------

from fastapi.security import APIKeyHeader

_end_user_key_header = APIKeyHeader(
    name="X-End-User-Key",
    auto_error=False,
)


def hash_api_key(key: str) -> str:
    """
    SHA-256, not a slow password hash (Argon2/bcrypt) - these are
    high-entropy generated keys (see storage_api.py's create_matter,
    secrets.token_urlsafe), not human-chosen passwords, so there's no
    brute-force-guessing risk a slow hash would need to defend against.
    """

    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def require_end_user_key(
    provided_key: str | None = Depends(_end_user_key_header),
) -> dict:
    """
    Resolves the caller to a Matter (an isolated End User identity -
    see app/metadata/base.py's matters methods, POST /admin/matters):
    {"id": int, "name": str}.

    Checks real per-matter keys first, then falls back to the single
    legacy END_USER_API_KEY (config/settings.py) as an implicit
    "Default" matter (id=0) - every existing caller and test that
    never created a Matter keeps working unchanged; real multi-matter
    isolation (POST /end-user/threads, etc.) is opt-in via
    POST /admin/matters.
    """

    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-End-User-Key header.",
        )

    from app.api import storage_api  # deferred: see end_user_api.py's _current_disclaimer_text() for why

    matter = storage_api.metadata_repository.get_matter_by_key_hash(hash_api_key(provided_key))
    if matter is not None:
        return {"id": matter["id"], "name": matter["name"]}

    expected_key = get_settings().end_user_api_key
    if secrets.compare_digest(provided_key, expected_key):
        return {"id": 0, "name": "Default"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid X-End-User-Key header.",
    )
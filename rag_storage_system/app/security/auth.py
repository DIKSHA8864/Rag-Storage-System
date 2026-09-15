"""
Authentication and authorization.

Owner/Admin:
    Email + password -> JWT access token -> Authorization: Bearer <token>

End User:
    Separate X-End-User-Key authentication remains unchanged for now.

The existing `require_admin_key` dependency name is intentionally kept
so storage_api.py does not need to change every protected endpoint.
"""

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


def require_end_user_key(
    provided_key: str | None = Depends(_end_user_key_header),
) -> None:
    """
    Existing separate End User authentication.

    This remains independent from Owner JWT authentication.
    """

    import secrets

    expected_key = get_settings().end_user_api_key

    if (
        not provided_key
        or not secrets.compare_digest(provided_key, expected_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-End-User-Key header.",
        )
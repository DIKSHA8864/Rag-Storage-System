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

def create_access_token(owner_id: int, email: str, tenant_id: int = 1, role: str = "owner") -> str:
    """
    Create a signed JWT access token for the Owner or firm staff
    (attorney/paralegal). `tenant_id` identifies which firm/organization
    this account belongs to (app/security/tenant_repository.py) - every
    Matter, document, and other tenant-owned resource this token can
    ever reach is checked against it (see ensure_matter_access() below).
    """

    settings = get_settings()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    payload = {
        "sub": str(owner_id),
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
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

    if payload.get("role") not in ("owner", "attorney", "paralegal"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner, attorney, or paralegal access required.",
        )

    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )

    tenant_id = payload.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing tenant context.",
        )
    payload["tenant_id"] = int(tenant_id)

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


def require_owner_role(owner: dict = Depends(require_admin_key)) -> dict:
    """
    FastAPI dependency for endpoints only the firm's Owner may use -
    today, that is billing/subscription management and the global
    plan catalog (app/api/billing_api.py). "attorney"/"paralegal" are
    valid Owner-JWT holders (require_admin_key above accepts them) but
    must not manage the firm's subscription.
    """

    if owner.get("role") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required.",
        )
    return owner


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
        return {"id": matter["id"], "name": matter["name"], "tenant_id": matter.get("tenant_id", 1)}

    expected_key = get_settings().end_user_api_key
    if secrets.compare_digest(provided_key, expected_key):
        return {"id": 0, "name": "Default", "tenant_id": 1}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid X-End-User-Key header.",
    )


def current_matter(matter: dict | None = Depends(require_end_user_key)) -> dict:
    """
    Thin wrapper around require_end_user_key, shared by
    app/api/end_user_api.py's threads and app/api/intake_api.py's
    intake sessions (moved here to avoid a circular import between the
    two routers). Falls back to the same implicit "Default" matter
    (id=0) tests get via conftest.py's dependency_overrides (which
    replaces require_end_user_key with a lambda returning None).
    """

    return matter if matter is not None else {"id": 0, "name": "Default", "tenant_id": 1}

# ----------------------------------------------------------------------
# Matter Workspace: role-based access to a Matter's data
# ----------------------------------------------------------------------

def ensure_matter_access(owner: dict, matter_id: int, metadata_repository) -> None:
    """
    Raise 403/404 unless `owner` (the decoded JWT payload) may act on
    `matter_id`.

    matter_id == 0 (or otherwise falsy) is the implicit "Default"
    matter (see app/security/auth.py's require_end_user_key() and
    app/report/rag_analysis.py's docstring) - it has no real row in
    `matters`, so there is no tenant to check it against. Owner-role
    passes immediately, same as always; no other role could ever have
    a matter_assignments row for a nonexistent Matter id, so this still
    404s for them exactly as it always has.

    For a real Matter id: tenant isolation is checked FIRST, for every
    role including "owner" - an Owner is the full admin of their OWN
    tenant/firm only, never a global superuser across every firm in
    the install. A Matter belonging to a different tenant 404s exactly
    like a nonexistent one, so this never even confirms another
    tenant's Matter exists.

    Within the same tenant: role == "owner" always passes;
    "attorney"/"paralegal" need a matter_assignments row (see
    database/migrations/0013_matter_workspace.sql) - assigned via
    POST /admin/matters/{matter_id}/assignments.
    """

    if not matter_id:
        if owner.get("role") == "owner":
            return
        raise HTTPException(status_code=404, detail="Matter not found.")

    matter = metadata_repository.get_matter(matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")

    if int(matter.get("tenant_id", 1)) != int(owner.get("tenant_id", 1)):
        raise HTTPException(status_code=404, detail="Matter not found.")

    if owner.get("role") == "owner":
        return

    assignment = metadata_repository.get_matter_assignment(int(owner["sub"]), matter_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this Matter.",
        )
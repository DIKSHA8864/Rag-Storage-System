"""
Individual end-user accounts - how a company's members (the End Users)
sign in, instead of sharing a per-Matter access code.

Lifecycle:
    invited      the Owner/Admin added this email (POST /admin/users);
                 nobody can sign up with an email that wasn't invited
    active       the user proved they own the inbox with a one-time
                 code and set their own password (signup), and can
                 now log in with email + password
    deactivated  the Owner/Admin switched the account off - every
                 existing session stops working immediately (see
                 session_version below), and login is refused

Each account gets its own personal Matter on activation, so the
existing Matter-scoped isolation (intake sessions, threads, Q&A
history - app/security/auth.py's current_matter) applies to every
user unchanged: one user can never see another user's history.

SECURITY NOTES:
  - Verification codes are 6 digits, expire after
    VERIFICATION_CODE_EXPIRE_MINUTES, allow MAX_CODE_ATTEMPTS wrong
    guesses before becoming unusable, and are stored only as an HMAC
    keyed by JWT_SECRET_KEY (a leaked database can't be brute-forced
    offline back into live codes).
  - Code-request endpoints always return the same generic response
    whether or not the email is invited/registered, so they can't be
    used to discover which emails have accounts.
  - Passwords use the same Argon2 hashing as the Owner login.
  - session_version is bumped on every password reset and every
    deactivation; each session token carries the version it was issued
    with, so either event invalidates all existing sessions at once.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.metadata.base import MetadataRepository
from app.security.auth import hash_api_key, hash_password, verify_password
from config.settings import get_settings

logger = logging.getLogger(__name__)

PURPOSE_SIGNUP = "signup"
PURPOSE_PASSWORD_RESET = "password_reset"

MAX_CODE_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60

STATUS_INVITED = "invited"
STATUS_ACTIVE = "active"
STATUS_DEACTIVATED = "deactivated"

_INVALID_CODE_MESSAGE = "Invalid or expired code. Request a new one and try again."
_INVALID_LOGIN_MESSAGE = "Invalid email or password."

_dummy_password_hash: Optional[str] = None


class AccountError(Exception):
    """A user-facing account error - its message is safe to return to the caller as-is."""


class AccountDeactivatedError(AccountError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hash_code(email: str, purpose: str, code: str) -> str:
    key = get_settings().jwt_secret_key.encode("utf-8")
    return hmac.new(key, f"{email}:{purpose}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def _send_email(to_email: str, subject: str, body: str) -> bool:
    from app.notifications.email_sender import get_email_sender

    try:
        get_email_sender().send(to_email, subject, body)
        return True
    except Exception:
        logger.exception("Could not send '%s' email to %s", subject, to_email)
        return False


# ----------------------------------------------------------------------
# Owner/Admin: invite, list, deactivate, reactivate
# ----------------------------------------------------------------------


def invite_end_users(
    repo: MetadataRepository, emails: list[str], tenant_id: int, invited_by: Optional[str]
) -> dict:
    """
    Invite every email in `emails` to `tenant_id`. Returns
    {"invited": [account, ...], "skipped": [{"email", "reason"}, ...]} -
    an email that already has an account (in any state) is skipped,
    never overwritten.
    """

    invited: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    signup_url = f"{get_settings().frontend_base_url.rstrip('/')}/portal/signup"

    for raw_email in emails:
        email = normalize_email(raw_email)
        if not email or email in seen:
            continue
        seen.add(email)

        existing = repo.get_end_user_by_email(email)
        if existing is not None:
            if existing["tenant_id"] != tenant_id:
                reason = "already registered"
            elif existing["status"] == STATUS_DEACTIVATED:
                reason = "deactivated - use Reactivate instead"
            else:
                reason = f"already {existing['status']}"
            skipped.append({"email": email, "reason": reason})
            continue

        account = repo.create_end_user_invite(email, tenant_id, invited_by)
        invited.append(account)

        _send_email(
            email,
            "You've been invited to AshiLegal",
            f"You've been invited to use AshiLegal.\n\n"
            f"Create your account here: {signup_url}\n\n"
            f"Sign up with this email address ({email}). We'll email you a one-time "
            f"code to confirm it's you, then you'll choose your own password.",
        )

    return {"invited": invited, "skipped": skipped}


def get_tenant_account(repo: MetadataRepository, end_user_id: int, tenant_id: int) -> Optional[dict]:
    """The account with this id, only if it belongs to `tenant_id` - so one tenant's admin can never touch another tenant's users."""

    account = repo.get_end_user(end_user_id)
    if account is None or account["tenant_id"] != tenant_id:
        return None
    return account


def deactivate(repo: MetadataRepository, account: dict) -> dict:
    return repo.set_end_user_status(account["id"], STATUS_DEACTIVATED)


def reactivate(repo: MetadataRepository, account: dict) -> dict:
    """Back to "active" if the user had already signed up, otherwise back to "invited" so they can still complete signup."""

    new_status = STATUS_ACTIVE if account.get("password_hash") else STATUS_INVITED
    return repo.set_end_user_status(account["id"], new_status)


# ----------------------------------------------------------------------
# End user: one-time codes, signup, login, password reset
# ----------------------------------------------------------------------


def request_code(repo: MetadataRepository, email: str, purpose: str) -> None:
    """
    Email a one-time code to `email` if - and only if - it is eligible
    for `purpose` (an invited account for signup, an active one for
    password reset). Deliberately returns nothing either way: the
    caller always gives the same generic response, so this can't be
    used to discover which emails have accounts.
    """

    email = normalize_email(email)
    account = repo.get_end_user_by_email(email)
    required_status = STATUS_INVITED if purpose == PURPOSE_SIGNUP else STATUS_ACTIVE

    if account is None or account["status"] != required_status:
        return

    latest = repo.get_latest_verification_code(email, purpose)
    if (
        latest is not None
        and latest["consumed_at"] is None
        and _now() - _as_datetime(latest["created_at"]) < timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    ):
        return

    settings = get_settings()
    code = f"{secrets.randbelow(10**6):06d}"
    repo.create_verification_code(
        email, purpose, _hash_code(email, purpose, code),
        _now() + timedelta(minutes=settings.verification_code_expire_minutes),
    )

    action = "create your AshiLegal account" if purpose == PURPOSE_SIGNUP else "reset your AshiLegal password"
    _send_email(
        email,
        f"Your AshiLegal code: {code}",
        f"Your one-time code to {action} is:\n\n    {code}\n\n"
        f"It expires in {settings.verification_code_expire_minutes} minutes. "
        f"If you didn't request this, you can ignore this email.",
    )


def _consume_valid_code(repo: MetadataRepository, email: str, purpose: str, code: str) -> bool:
    record = repo.get_latest_verification_code(email, purpose)

    if (
        record is None
        or record["consumed_at"] is not None
        or record["attempts"] >= MAX_CODE_ATTEMPTS
        or _now() >= _as_datetime(record["expires_at"])
    ):
        return False

    if not hmac.compare_digest(record["code_hash"], _hash_code(email, purpose, code.strip())):
        repo.increment_verification_attempts(record["id"])
        return False

    repo.consume_verification_code(record["id"], _now())
    return True


def complete_signup(repo: MetadataRepository, email: str, code: str, password: str) -> dict:
    """Verify the signup code, set the password, create the user's personal Matter, and activate the account."""

    email = normalize_email(email)
    account = repo.get_end_user_by_email(email)

    if account is None or account["status"] != STATUS_INVITED:
        raise AccountError(_INVALID_CODE_MESSAGE)

    if not _consume_valid_code(repo, email, PURPOSE_SIGNUP, code):
        raise AccountError(_INVALID_CODE_MESSAGE)

    matter_id = account.get("matter_id")
    if not matter_id:
        # The Matter's X-End-User-Key is generated and immediately
        # discarded - this account signs in with its own password, so
        # no shared key for its personal Matter should exist anywhere.
        matter = repo.create_matter(email, hash_api_key(secrets.token_urlsafe(32)), tenant_id=account["tenant_id"])
        matter_id = matter["id"]

    return repo.activate_end_user(account["id"], hash_password(password), matter_id, _now())


def authenticate(repo: MetadataRepository, email: str, password: str) -> dict:
    global _dummy_password_hash

    email = normalize_email(email)
    account = repo.get_end_user_by_email(email)

    if account is None or not account.get("password_hash"):
        # Spend the same Argon2 time as a real check, so response
        # timing doesn't reveal whether the email has an account.
        if _dummy_password_hash is None:
            _dummy_password_hash = hash_password(secrets.token_urlsafe(16))
        verify_password(password, _dummy_password_hash)
        raise AccountError(_INVALID_LOGIN_MESSAGE)

    if not verify_password(password, account["password_hash"]):
        raise AccountError(_INVALID_LOGIN_MESSAGE)

    if account["status"] != STATUS_ACTIVE:
        raise AccountDeactivatedError("This account has been deactivated. Contact your administrator.")

    return account


def complete_password_reset(repo: MetadataRepository, email: str, code: str, new_password: str) -> dict:
    email = normalize_email(email)
    account = repo.get_end_user_by_email(email)

    if account is None or account["status"] != STATUS_ACTIVE:
        raise AccountError(_INVALID_CODE_MESSAGE)

    if not _consume_valid_code(repo, email, PURPOSE_PASSWORD_RESET, code):
        raise AccountError(_INVALID_CODE_MESSAGE)

    return repo.update_end_user_password(account["id"], hash_password(new_password))

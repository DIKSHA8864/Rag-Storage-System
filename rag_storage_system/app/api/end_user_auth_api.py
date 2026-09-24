"""
End-user account sign-up / sign-in (app/security/end_user_accounts.py).
Public (no credential needed to reach them) - but only an email the
Owner/Admin invited (POST /admin/users) can ever complete signup, and
every endpoint is rate-limited per client IP.

Endpoints:
    POST /end-user/auth/signup/request-code           email a one-time signup code (invited emails only)
    POST /end-user/auth/signup/complete               code + new password -> account active, signed in
    POST /end-user/auth/login                         email + password -> signed in
    POST /end-user/auth/password-reset/request-code   email a one-time reset code (active accounts only)
    POST /end-user/auth/password-reset/complete       code + new password (signs out every other session)
    GET  /end-user/auth/me                            the signed-in account

The two request-code endpoints always return the same response
whether or not the email is invited/registered, so they can't be used
to find out who has an account.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import (
    EndUserEmailRequest,
    EndUserLoginRequest,
    EndUserMeResponse,
    EndUserPasswordResetCompleteRequest,
    EndUserSessionResponse,
    EndUserSignupCompleteRequest,
    GenericMessageResponse,
)
from app.security import end_user_accounts
from app.security.auth import create_end_user_token, require_end_user_account
from app.security.rate_limit import limiter
from config.settings import get_settings

router = APIRouter(prefix="/end-user/auth", tags=["end-user-auth"])

_CODE_SENT_MESSAGE = (
    "If this email is eligible, a 6-digit code has been sent to it. "
    "It expires in a few minutes - check your inbox (and spam folder)."
)


def _session(account: dict) -> EndUserSessionResponse:
    return EndUserSessionResponse(
        access_token=create_end_user_token(
            account["id"], account["email"], account["tenant_id"], account["session_version"]
        ),
        expires_in=get_settings().end_user_token_expire_minutes * 60,
        email=account["email"],
    )


@router.post("/signup/request-code", response_model=GenericMessageResponse)
@limiter.limit("5/minute")
def request_signup_code(request: Request, body: EndUserEmailRequest) -> GenericMessageResponse:
    from app.api import storage_api

    end_user_accounts.request_code(storage_api.metadata_repository, str(body.email), end_user_accounts.PURPOSE_SIGNUP)
    return GenericMessageResponse(detail=_CODE_SENT_MESSAGE)


@router.post("/signup/complete", response_model=EndUserSessionResponse)
@limiter.limit("10/minute")
def complete_signup(request: Request, body: EndUserSignupCompleteRequest) -> EndUserSessionResponse:
    from app.api import storage_api

    try:
        account = end_user_accounts.complete_signup(
            storage_api.metadata_repository, str(body.email), body.code, body.password
        )
    except end_user_accounts.AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _session(account)


@router.post("/login", response_model=EndUserSessionResponse)
@limiter.limit("5/minute")
def login(request: Request, body: EndUserLoginRequest) -> EndUserSessionResponse:
    from app.api import storage_api

    try:
        account = end_user_accounts.authenticate(storage_api.metadata_repository, str(body.email), body.password)
    except end_user_accounts.AccountDeactivatedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except end_user_accounts.AccountError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return _session(account)


@router.post("/password-reset/request-code", response_model=GenericMessageResponse)
@limiter.limit("5/minute")
def request_password_reset_code(request: Request, body: EndUserEmailRequest) -> GenericMessageResponse:
    from app.api import storage_api

    end_user_accounts.request_code(
        storage_api.metadata_repository, str(body.email), end_user_accounts.PURPOSE_PASSWORD_RESET
    )
    return GenericMessageResponse(detail=_CODE_SENT_MESSAGE)


@router.post("/password-reset/complete", response_model=GenericMessageResponse)
@limiter.limit("10/minute")
def complete_password_reset(request: Request, body: EndUserPasswordResetCompleteRequest) -> GenericMessageResponse:
    from app.api import storage_api

    try:
        end_user_accounts.complete_password_reset(
            storage_api.metadata_repository, str(body.email), body.code, body.new_password
        )
    except end_user_accounts.AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return GenericMessageResponse(detail="Password updated. Please log in with your new password.")


@router.get("/me", response_model=EndUserMeResponse)
def me(account: dict = Depends(require_end_user_account)) -> EndUserMeResponse:
    return EndUserMeResponse(id=account["id"], email=account["email"], status=account["status"])

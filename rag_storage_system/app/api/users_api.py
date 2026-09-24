"""
End-user account management for the Owner/Admin
(app/security/end_user_accounts.py). Owner role only
(app/security/auth.py's require_owner_role) - attorneys/paralegals and
end users can never reach these. Every endpoint only ever touches the
caller's own tenant's users; another tenant's user id 404s.

Endpoints:
    GET  /admin/users                       list this tenant's end users
    POST /admin/users                       invite one or more emails
    POST /admin/users/{id}/deactivate       switch an account off (ends every session immediately)
    POST /admin/users/{id}/reactivate       switch it back on
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import (
    EndUserAccountInfo,
    EndUserListResponse,
    InviteEndUsersRequest,
    InviteEndUsersResponse,
    InviteSkippedEmail,
)
from app.security import end_user_accounts
from app.security.audit_log import log_audit_event
from app.security.auth import require_owner_role

router = APIRouter(prefix="/admin/users", tags=["user-management"], dependencies=[Depends(require_owner_role)])


def _account_info(account: dict) -> EndUserAccountInfo:
    return EndUserAccountInfo(
        id=account["id"],
        email=account["email"],
        status=account["status"],
        invited_by=account.get("invited_by"),
        created_at=str(account["created_at"]),
        activated_at=str(account["activated_at"]) if account.get("activated_at") else None,
    )


def _owned_account(end_user_id: int, owner: dict) -> dict:
    from app.api import storage_api

    account = end_user_accounts.get_tenant_account(storage_api.metadata_repository, end_user_id, owner["tenant_id"])
    if account is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return account


@router.get("", response_model=EndUserListResponse)
def list_users(owner: dict = Depends(require_owner_role)) -> EndUserListResponse:
    from app.api import storage_api

    accounts = storage_api.metadata_repository.list_end_users(owner["tenant_id"])
    return EndUserListResponse(users=[_account_info(a) for a in accounts])


@router.post("", response_model=InviteEndUsersResponse)
def invite_users(request: InviteEndUsersRequest, owner: dict = Depends(require_owner_role)) -> InviteEndUsersResponse:
    """Invite emails - only an invited email can ever complete signup. Each invitee gets an email with the signup link."""

    from app.api import storage_api

    result = end_user_accounts.invite_end_users(
        storage_api.metadata_repository, [str(e) for e in request.emails], owner["tenant_id"], owner.get("email"),
    )

    for account in result["invited"]:
        log_audit_event("invite_end_user", detail=account["email"], actor=owner.get("email") or "admin")

    return InviteEndUsersResponse(
        invited=[_account_info(a) for a in result["invited"]],
        skipped=[InviteSkippedEmail(**s) for s in result["skipped"]],
    )


@router.post("/{end_user_id}/deactivate", response_model=EndUserAccountInfo)
def deactivate_user(end_user_id: int, owner: dict = Depends(require_owner_role)) -> EndUserAccountInfo:
    from app.api import storage_api

    account = _owned_account(end_user_id, owner)
    updated = end_user_accounts.deactivate(storage_api.metadata_repository, account)
    log_audit_event("deactivate_end_user", detail=account["email"], actor=owner.get("email") or "admin")
    return _account_info(updated)


@router.post("/{end_user_id}/reactivate", response_model=EndUserAccountInfo)
def reactivate_user(end_user_id: int, owner: dict = Depends(require_owner_role)) -> EndUserAccountInfo:
    from app.api import storage_api

    account = _owned_account(end_user_id, owner)
    if account["status"] != end_user_accounts.STATUS_DEACTIVATED:
        raise HTTPException(status_code=400, detail="This account is not deactivated.")

    updated = end_user_accounts.reactivate(storage_api.metadata_repository, account)
    log_audit_event("reactivate_end_user", detail=account["email"], actor=owner.get("email") or "admin")
    return _account_info(updated)

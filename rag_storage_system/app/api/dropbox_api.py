"""
The owner connects their own Dropbox and picks the folders that become the
library - from the Vault page, with no server settings to edit (Blueprint
Phase 1: files added to the vault reach the library "with no developer
involvement").

    GET    /admin/dropbox                     connection status + chosen folders
    POST   /admin/dropbox/connect             -> Dropbox's sign-in page (authorize_url)
    POST   /admin/dropbox/connect/complete    the code Dropbox sent back (the /vault/dropbox page posts it)
    GET    /admin/dropbox/folders?path=       the folders inside one Dropbox folder, for the picker
    PUT    /admin/dropbox/folders             the folders to sync (each becomes a library folder)
    DELETE /admin/dropbox                     disconnect (the library keeps its files)

Owner only, per organization. The OAuth `state` is signed and bound to the
organization and the owner who started it, and expires in 10 minutes, so
a code from someone else's sign-in can't be attached to this organization.
The refresh token is stored encrypted (app/security/secret_box.py).
"""

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import (
    DropboxConnectCompleteRequest,
    DropboxConnectResponse,
    DropboxFolderChoice,
    DropboxFolderEntry,
    DropboxFolderListResponse,
    DropboxFoldersUpdateRequest,
    DropboxStatusResponse,
)
from app.security.audit_log import log_audit_event
from app.security.auth import require_owner_role
from app.security.secret_box import SecretUnreadable, decrypt, encrypt
from app.vault_sync.dropbox_account import DropboxAccount, authorize_url, normalize_path
from app.vault_sync.dropbox_source import DropboxError
from app.vault_sync.runner import connected_mirror_dir, folder_labels
from config.settings import get_settings

router = APIRouter(prefix="/admin/dropbox", tags=["dropbox"], dependencies=[Depends(require_owner_role)])

STATE_PURPOSE = "dropbox_connect"
STATE_MINUTES = 10
MAX_FOLDERS = 20


def _repo():
    from app.api import storage_api

    return storage_api.metadata_repository


def redirect_uri() -> str:
    return get_settings().frontend_base_url.rstrip("/") + "/vault/dropbox"


def _available() -> bool:
    settings = get_settings()
    return bool(settings.dropbox_app_key and settings.dropbox_app_secret)


def _account(refresh_token: str | None = None) -> DropboxAccount:
    """A client for the AshiLegal Dropbox app. Tests replace this to use a fake Dropbox."""

    settings = get_settings()
    return DropboxAccount(settings.dropbox_app_key, settings.dropbox_app_secret, refresh_token)


def _connected_account(tenant_id: int) -> DropboxAccount:
    connection = _repo().get_dropbox_connection(tenant_id)
    if connection is None:
        raise HTTPException(status_code=409, detail="Dropbox isn't connected. Connect it first.")
    try:
        return _account(decrypt(connection["refresh_token_encrypted"]))
    except SecretUnreadable:
        raise HTTPException(status_code=409, detail="The saved Dropbox connection can't be read any more - please reconnect.")


def _status(tenant_id: int) -> DropboxStatusResponse:
    connection = _repo().get_dropbox_connection(tenant_id)
    base = {"available": _available(), "redirect_uri": redirect_uri()}
    if connection is None:
        return DropboxStatusResponse(connected=False, **base)
    try:
        decrypt(connection["refresh_token_encrypted"])
        needs_reconnect = False
    except SecretUnreadable:
        needs_reconnect = True
    labels = folder_labels(connection["folders"])
    return DropboxStatusResponse(
        connected=True, needs_reconnect=needs_reconnect, account_name=connection.get("account_name"),
        account_email=connection.get("account_email"), connected_by=connection.get("connected_by"),
        connected_at=str(connection["connected_at"]),
        folders=[DropboxFolderChoice(path=path, library_folder=labels[path]) for path in connection["folders"]],
        **base,
    )


def _dropbox_failure(exc: DropboxError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@router.get("", response_model=DropboxStatusResponse)
def dropbox_status(owner: dict = Depends(require_owner_role)) -> DropboxStatusResponse:
    return _status(owner["tenant_id"])


@router.post("/connect", response_model=DropboxConnectResponse)
def start_connect(owner: dict = Depends(require_owner_role)) -> DropboxConnectResponse:
    if not _available():
        raise HTTPException(
            status_code=409,
            detail="Dropbox isn't set up on this server yet: the AshiLegal Dropbox app key and secret are missing.",
        )
    settings = get_settings()
    state = jwt.encode(
        {
            "purpose": STATE_PURPOSE,
            "tenant_id": owner["tenant_id"],
            "sub": str(owner.get("sub")),
            "nonce": secrets.token_urlsafe(16),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=STATE_MINUTES),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return DropboxConnectResponse(authorize_url=authorize_url(settings.dropbox_app_key, redirect_uri(), state))


@router.post("/connect/complete", response_model=DropboxStatusResponse)
def complete_connect(request: DropboxConnectCompleteRequest, owner: dict = Depends(require_owner_role)) -> DropboxStatusResponse:
    settings = get_settings()
    try:
        state = jwt.decode(request.state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="This Dropbox sign-in link has expired or isn't valid. Please connect again.")
    if (
        state.get("purpose") != STATE_PURPOSE
        or state.get("tenant_id") != owner["tenant_id"]
        or state.get("sub") != str(owner.get("sub"))
    ):
        raise HTTPException(status_code=400, detail="This Dropbox sign-in was started by someone else. Please connect again.")

    try:
        account = _account()
        refresh_token = account.exchange_code(request.code, redirect_uri())
        details = account.account()
    except DropboxError as exc:
        raise _dropbox_failure(exc)

    repo = _repo()
    previous = repo.get_dropbox_connection(owner["tenant_id"])
    # Reconnecting the same Dropbox keeps the chosen folders; a different account starts with none.
    folders = previous["folders"] if previous and previous["account_id"] == details["account_id"] else []
    repo.save_dropbox_connection(
        owner["tenant_id"], details["account_id"], details["name"], details["email"], encrypt(refresh_token),
        folders, owner.get("email"),
    )
    log_audit_event("dropbox_connected", detail=f"account {details['email'] or details['account_id']}",
                    actor=owner.get("email") or "owner")
    return _status(owner["tenant_id"])


@router.get("/folders", response_model=DropboxFolderListResponse)
def list_folders(path: str = Query("", max_length=1000), owner: dict = Depends(require_owner_role)) -> DropboxFolderListResponse:
    account = _connected_account(owner["tenant_id"])
    try:
        path = normalize_path(path)
        folders = account.list_subfolders(path)
    except DropboxError as exc:
        raise _dropbox_failure(exc)
    chosen = {p.lower() for p in _repo().get_dropbox_connection(owner["tenant_id"])["folders"]}
    parent = None if not path else (path.rsplit("/", 1)[0] or "")
    return DropboxFolderListResponse(
        path=path,
        parent=parent,
        folders=[DropboxFolderEntry(name=f["name"], path=f["path"], selected=f["path"].lower() in chosen) for f in folders],
    )


@router.put("/folders", response_model=DropboxStatusResponse)
def choose_folders(request: DropboxFoldersUpdateRequest, owner: dict = Depends(require_owner_role)) -> DropboxStatusResponse:
    if len(request.paths) > MAX_FOLDERS:
        raise HTTPException(status_code=400, detail=f"Choose at most {MAX_FOLDERS} folders.")
    account = _connected_account(owner["tenant_id"])

    chosen: list[str] = []
    try:
        for raw in request.paths:
            path = account.folder_path(raw)  # confirms it exists and is a folder; Dropbox's own spelling
            if path.lower() not in {c.lower() for c in chosen}:
                chosen.append(path)
    except DropboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # A folder inside another chosen folder would be synced twice.
    for path in chosen:
        for other in chosen:
            if other != path and path.lower().startswith(other.lower() + "/"):
                raise HTTPException(
                    status_code=400,
                    detail=f"'{path}' is inside '{other}', which is already chosen - its files sync with it.",
                )

    _repo().set_dropbox_folders(owner["tenant_id"], chosen, owner.get("email"))
    log_audit_event("dropbox_folders_chosen", detail="; ".join(chosen) or "(none)", actor=owner.get("email") or "owner")
    return _status(owner["tenant_id"])


@router.delete("", response_model=DropboxStatusResponse)
def disconnect(owner: dict = Depends(require_owner_role)) -> DropboxStatusResponse:
    import shutil

    repo = _repo()
    connection = repo.get_dropbox_connection(owner["tenant_id"])
    if connection is None:
        return _status(owner["tenant_id"])
    try:
        _account(decrypt(connection["refresh_token_encrypted"])).revoke()
    except (SecretUnreadable, DropboxError):
        pass  # disconnecting still works; the token is dropped here either way
    repo.delete_dropbox_connection(owner["tenant_id"])
    shutil.rmtree(connected_mirror_dir(get_settings(), owner["tenant_id"]), ignore_errors=True)
    log_audit_event("dropbox_disconnected", actor=owner.get("email") or "owner")
    return _status(owner["tenant_id"])

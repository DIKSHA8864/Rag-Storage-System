"""
The owner's own Dropbox account, connected from the Vault page instead of
server settings (Blueprint Phase 1: the owner adds files to the vault
"with no developer involvement").

- connect: Dropbox's OAuth 2 code flow. The owner signs in on Dropbox's own
  page and allows AshiLegal; we exchange the returned code for a refresh
  token (token_access_type=offline) and keep it encrypted per organization.
  Only DROPBOX_APP_KEY / DROPBOX_APP_SECRET (the AshiLegal app registered
  once in Dropbox's App Console) are server settings.
- browse: list the sub-folders of a folder, so the owner can pick which
  folders become library folders.
- revoke: on Disconnect, tell Dropbox to cancel the token.

Needs a "Full Dropbox" app with files.metadata.read, files.content.read and
account_info.read, and the redirect URI {FRONTEND_BASE_URL}/vault/dropbox.
"""

from urllib.parse import urlencode

import requests

from app.vault_sync.dropbox_source import DropboxError, LIST_CONTINUE_PATH, LIST_PATH, TOKEN_PATH, _api
from config.settings import get_settings

ACCOUNT_PATH = "/2/users/get_current_account"
METADATA_PATH = "/2/files/get_metadata"
REVOKE_PATH = "/2/auth/token/revoke"

_MAX_FOLDERS_LISTED = 500


def authorize_url(app_key: str, redirect_uri: str, state: str) -> str:
    query = {
        "client_id": app_key,
        "response_type": "code",
        "token_access_type": "offline",  # a refresh token, so sync keeps working after the owner leaves
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{get_settings().dropbox_web_base.rstrip('/')}/oauth2/authorize?{urlencode(query)}"


def normalize_path(path: str) -> str:
    """Dropbox paths: "" is the root, everything else starts with "/" and has no trailing slash."""

    path = (path or "").strip().replace("\\", "/")
    parts = [part for part in path.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise DropboxError("That isn't a valid Dropbox folder path.")
    return "/" + "/".join(parts) if parts else ""


class DropboxAccount:
    def __init__(self, app_key: str, app_secret: str, refresh_token: str | None = None,
                 session: requests.Session | None = None, timeout: float = 30):
        if not (app_key and app_secret):
            raise DropboxError("Dropbox isn't available: DROPBOX_APP_KEY and DROPBOX_APP_SECRET are not set.")
        self._app_key, self._app_secret = app_key, app_secret
        self.refresh_token = refresh_token
        self._session = session or requests.Session()
        self._timeout = timeout
        self._access_token: str | None = None

    # ------------------------------------------------------------------

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """Finish the OAuth flow: returns (and keeps) the long-lived refresh token."""

        response = self._session.post(
            _api(TOKEN_PATH),
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
            auth=(self._app_key, self._app_secret),
            timeout=self._timeout,
        )
        if response.status_code != 200:
            raise DropboxError(f"Dropbox didn't accept the sign-in ({response.status_code}). Please try connecting again.")
        body = response.json()
        if not body.get("refresh_token"):
            raise DropboxError("Dropbox didn't return a long-lived token. Please try connecting again.")
        self.refresh_token, self._access_token = body["refresh_token"], body.get("access_token")
        return self.refresh_token

    def _token(self) -> str:
        if self._access_token is None:
            if not self.refresh_token:
                raise DropboxError("Dropbox isn't connected.")
            response = self._session.post(
                _api(TOKEN_PATH),
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                auth=(self._app_key, self._app_secret),
                timeout=self._timeout,
            )
            if response.status_code != 200:
                raise DropboxError(
                    "Dropbox refused the saved connection - it may have been removed in Dropbox. Please reconnect."
                )
            self._access_token = response.json()["access_token"]
        return self._access_token

    def _rpc(self, url: str, body: dict | None) -> dict:
        response = self._session.post(
            url, json=body, headers={"Authorization": f"Bearer {self._token()}"}, timeout=self._timeout
        )
        if response.status_code == 409:
            raise DropboxError("That folder wasn't found in Dropbox.")
        if response.status_code != 200:
            raise DropboxError(f"Dropbox request failed ({response.status_code}).")
        return response.json() if response.content else {}

    # ------------------------------------------------------------------

    def account(self) -> dict:
        """{"account_id", "name", "email"} of the connected Dropbox account."""

        body = self._rpc(_api(ACCOUNT_PATH), None)
        return {
            "account_id": body.get("account_id", ""),
            "name": (body.get("name") or {}).get("display_name"),
            "email": body.get("email"),
        }

    def list_subfolders(self, path: str) -> list[dict]:
        """The folders directly inside `path` ("" = the top of the Dropbox), sorted by name."""

        page = self._rpc(_api(LIST_PATH), {"path": normalize_path(path), "recursive": False, "include_deleted": False})
        entries = list(page.get("entries", []))
        while page.get("has_more") and len(entries) < _MAX_FOLDERS_LISTED:
            page = self._rpc(_api(LIST_CONTINUE_PATH), {"cursor": page["cursor"]})
            entries.extend(page.get("entries", []))
        folders = [
            {"name": entry["name"], "path": entry["path_display"]}
            for entry in entries if entry.get(".tag") == "folder"
        ]
        return sorted(folders, key=lambda folder: folder["name"].lower())

    def folder_path(self, path: str) -> str:
        """Dropbox's own spelling (path_display) of an existing folder; DropboxError if it isn't one."""

        path = normalize_path(path)
        if not path:
            raise DropboxError("Choose a folder inside your Dropbox, not the whole Dropbox.")
        body = self._rpc(_api(METADATA_PATH), {"path": path})
        if body.get(".tag") != "folder":
            raise DropboxError(f"'{path}' isn't a folder in Dropbox.")
        return body["path_display"]

    def revoke(self) -> None:
        """Best effort: cancel the token in Dropbox. Disconnecting works even if this fails."""

        try:
            self._rpc(_api(REVOKE_PATH), None)
        except DropboxError:
            pass

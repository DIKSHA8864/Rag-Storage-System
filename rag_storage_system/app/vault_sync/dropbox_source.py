"""
Dropbox API source for vault sync: keeps a local mirror folder identical to
a Dropbox folder, which app/vault_sync/folder_sync.py then syncs into the
library - so a Dropbox folder the server can't mount directly still works.

Uses Dropbox's HTTP API v2 with a long-lived refresh token (the owner's
Dropbox app: DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN,
optionally DROPBOX_ROOT_PATH). Polling (Blueprint Work Plan M1: "Dropbox
API webhook (fallback: 5-minute polling)") - run it on a schedule with
scripts/vault_sync.py --watch. Only files whose Dropbox revision changed
are downloaded again.
"""

import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
LIST_URL = "https://api.dropboxapi.com/2/files/list_folder"
LIST_CONTINUE_URL = "https://api.dropboxapi.com/2/files/list_folder/continue"
DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"

INDEX_FILENAME = ".dropbox_index.json"  # hidden: folder_sync ignores dot-files


class DropboxError(Exception):
    pass


class DropboxMirror:
    def __init__(
        self, app_key: str, app_secret: str, refresh_token: str, root_path: str, mirror_dir: Path,
        session: requests.Session | None = None, timeout: float = 60,
    ):
        if not (app_key and app_secret and refresh_token):
            raise DropboxError("DROPBOX_APP_KEY, DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN must all be set.")
        self._app_key, self._app_secret, self._refresh_token = app_key, app_secret, refresh_token
        self._root = "/" + root_path.strip("/") if root_path.strip("/") else ""
        self._mirror_dir = Path(mirror_dir)
        self._session = session or requests.Session()
        self._timeout = timeout
        self._access_token: str | None = None

    # ------------------------------------------------------------------

    def _token(self) -> str:
        if self._access_token is None:
            response = self._session.post(
                TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
                auth=(self._app_key, self._app_secret),
                timeout=self._timeout,
            )
            if response.status_code != 200:
                raise DropboxError(f"Dropbox sign-in failed ({response.status_code}): {response.text[:200]}")
            self._access_token = response.json()["access_token"]
        return self._access_token

    def _rpc(self, url: str, body: dict) -> dict:
        response = self._session.post(
            url, json=body, headers={"Authorization": f"Bearer {self._token()}"}, timeout=self._timeout
        )
        if response.status_code != 200:
            raise DropboxError(f"Dropbox request failed ({response.status_code}): {response.text[:200]}")
        return response.json()

    def _list_files(self) -> dict[str, dict]:
        """relative path (as shown in Dropbox) -> file entry, for every file under the root."""

        page = self._rpc(LIST_URL, {"path": self._root, "recursive": True, "include_deleted": False})
        entries = list(page["entries"])
        while page.get("has_more"):
            page = self._rpc(LIST_CONTINUE_URL, {"cursor": page["cursor"]})
            entries.extend(page["entries"])

        files = {}
        prefix_length = len(self._root) + 1 if self._root else 1
        for entry in entries:
            if entry.get(".tag") != "file":
                continue
            relative = entry["path_display"][prefix_length:]
            if relative and ".." not in Path(relative).parts:
                files[relative] = entry
        return files

    def _download(self, entry: dict) -> bytes:
        response = self._session.post(
            DOWNLOAD_URL,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Dropbox-API-Arg": json.dumps({"path": entry["path_lower"]}),
            },
            timeout=self._timeout,
        )
        if response.status_code != 200:
            raise DropboxError(f"Downloading '{entry['path_display']}' failed ({response.status_code}).")
        return response.content

    # ------------------------------------------------------------------

    def refresh(self) -> dict:
        """Bring the mirror folder in line with Dropbox. Returns {"downloaded", "removed", "unchanged"}."""

        self._mirror_dir.mkdir(parents=True, exist_ok=True)
        index_path = self._mirror_dir / INDEX_FILENAME
        index: dict[str, str] = json.loads(index_path.read_text()) if index_path.exists() else {}

        remote = self._list_files()
        counts = {"downloaded": 0, "removed": 0, "unchanged": 0}

        for relative, entry in remote.items():
            local = self._mirror_dir / relative
            if index.get(relative) == entry["rev"] and local.exists():
                counts["unchanged"] += 1
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            partial = local.with_name(local.name + ".part")
            partial.write_bytes(self._download(entry))
            os.replace(partial, local)
            index[relative] = entry["rev"]
            counts["downloaded"] += 1

        for relative in [path for path in index if path not in remote]:
            (self._mirror_dir / relative).unlink(missing_ok=True)
            del index[relative]
            counts["removed"] += 1

        index_path.write_text(json.dumps(index, indent=1))
        logger.info("Dropbox mirror refreshed: %s", counts)
        return counts

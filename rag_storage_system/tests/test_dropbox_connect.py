"""
"Connect Dropbox + choose folders" (app/api/dropbox_api.py, app/vault_sync/
dropbox_account.py, runner.py): the owner connects their own Dropbox on the
Vault page and ticks the folders that become the library - no server
settings. Dropbox itself is a fake HTTP session.
"""

import json as jsonlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.security.auth import create_access_token, require_admin_key
from app.vault_sync import dropbox_account, dropbox_source
from app.vault_sync.runner import folder_labels, run_vault_sync, synced_tenant_ids
from config.settings import get_settings
from tests.test_vault_sync import env  # noqa: F401 - shared fixture


class _Response:
    def __init__(self, body=None, content=b"", status_code=200):
        self._body, self.content, self.status_code, self.text = body, content, status_code, ""
        if body is not None and not content:
            self.content = b"{}"

    def json(self):
        return self._body


class FakeDropbox:
    """Just enough of Dropbox's HTTP API v2: OAuth code + refresh, account, list_folder, metadata, download, revoke."""

    def __init__(self):
        self.folders = {"/Clients", "/Clients/Diksha", "/Clients/Diksha/Wage", "/Firm Library", "/Personal"}
        self.files = {}  # path_display -> (rev, bytes)
        self.revoked = False
        self.codes = {"good-code": "refresh-A"}

    def _file_entries(self, root, recursive):
        prefix = root.lower() + "/"
        entries = []
        for path in sorted(self.folders):
            if path.lower().startswith(prefix) and (recursive or "/" not in path[len(prefix):]):
                entries.append({".tag": "folder", "name": path.rsplit("/", 1)[-1], "path_display": path,
                                "path_lower": path.lower()})
        for path, (rev, _) in sorted(self.files.items()):
            if path.lower().startswith(prefix) and (recursive or "/" not in path[len(prefix):]):
                entries.append({".tag": "file", "name": path.rsplit("/", 1)[-1], "path_display": path,
                                "path_lower": path.lower(), "rev": rev})
        return entries

    def post(self, url, json=None, data=None, headers=None, auth=None, timeout=None):
        if url.endswith("/oauth2/token"):
            assert auth == ("app-key", "app-secret")
            if data["grant_type"] == "authorization_code":
                assert data["redirect_uri"] == "http://portal.test/vault/dropbox"
                if data["code"] not in self.codes:
                    return _Response({"error": "invalid_grant"}, status_code=400)
                return _Response({"access_token": "tok", "refresh_token": self.codes[data["code"]]})
            assert data["grant_type"] == "refresh_token"
            if data["refresh_token"] != "refresh-A" or self.revoked:
                return _Response({"error": "invalid_grant"}, status_code=400)
            return _Response({"access_token": "tok"})
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/users/get_current_account"):
            return _Response({"account_id": "dbid:A", "name": {"display_name": "Diksha K"}, "email": "diksha@firm.com"})
        if url.endswith("/files/list_folder"):
            return _Response({"entries": self._file_entries(json["path"], json["recursive"]), "cursor": "c", "has_more": False})
        if url.endswith("/files/get_metadata"):
            match = next((p for p in self.folders if p.lower() == json["path"].lower()), None)
            if match:
                return _Response({".tag": "folder", "path_display": match})
            if any(p.lower() == json["path"].lower() for p in self.files):
                return _Response({".tag": "file", "path_display": json["path"]})
            return _Response({"error": "not_found"}, status_code=409)
        if url.endswith("/files/download"):
            path = jsonlib.loads(headers["Dropbox-API-Arg"])["path"]
            return _Response(content=next(b for p, (_, b) in self.files.items() if p.lower() == path))
        if url.endswith("/auth/token/revoke"):
            self.revoked = True
            return _Response({})
        raise AssertionError(url)


@pytest.fixture
def dropbox(monkeypatch):
    fake = FakeDropbox()
    fake_requests = SimpleNamespace(Session=lambda: fake)
    monkeypatch.setattr(dropbox_account, "requests", fake_requests)
    monkeypatch.setattr(dropbox_source, "requests", fake_requests)
    return fake


@pytest.fixture
def api(env, dropbox, tmp_path, monkeypatch):  # noqa: F811 - env is the shared fixture
    settings = get_settings()
    for key, value in {
        "dropbox_app_key": "app-key", "dropbox_app_secret": "app-secret", "dropbox_refresh_token": "",
        "vault_sync_dir": "", "frontend_base_url": "http://portal.test",
        "vault_mirror_dir": str(tmp_path / "vault_mirror"),
    }.items():
        monkeypatch.setattr(settings, key, value)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", env.repo)
    monkeypatch.setattr(storage_api, "storage_backend", env.storage)
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _as(tenant_id=1, role="owner", owner_id=1):
    token = create_access_token(owner_id=owner_id, email=f"{role}@firm.com", tenant_id=tenant_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _connect(api, headers=None):
    headers = headers or _as()
    url = api.post("/admin/dropbox/connect", headers=headers).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return api.post("/admin/dropbox/connect/complete", json={"code": "good-code", "state": state}, headers=headers)


def test_connect_flow_stores_an_encrypted_token_and_the_account(api, env):
    assert api.get("/admin/dropbox", headers=_as()).json() == {
        "available": True, "redirect_uri": "http://portal.test/vault/dropbox", "connected": False,
        "needs_reconnect": False, "account_name": None, "account_email": None, "connected_by": None,
        "connected_at": None, "folders": [],
    }

    url = api.post("/admin/dropbox/connect", headers=_as()).json()["authorize_url"]
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.dropbox.com/oauth2/authorize?")
    assert query["client_id"] == ["app-key"] and query["token_access_type"] == ["offline"]
    assert query["redirect_uri"] == ["http://portal.test/vault/dropbox"]

    status = _connect(api).json()
    assert status["connected"] is True and status["account_email"] == "diksha@firm.com"
    stored = env.repo.get_dropbox_connection(1)
    assert stored["refresh_token_encrypted"] != "refresh-A" and "refresh-A" not in stored["refresh_token_encrypted"]


def test_a_sign_in_started_by_someone_else_or_expired_is_refused(api):
    url = api.post("/admin/dropbox/connect", headers=_as()).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]

    # another organization's owner, or another owner, can't finish it
    for headers in (_as(tenant_id=2), _as(owner_id=9)):
        response = api.post("/admin/dropbox/connect/complete", json={"code": "good-code", "state": state}, headers=headers)
        assert response.status_code == 400
    bad = api.post("/admin/dropbox/connect/complete", json={"code": "good-code", "state": "forged"}, headers=_as())
    assert bad.status_code == 400
    wrong_code = api.post("/admin/dropbox/connect/complete", json={"code": "nope", "state": state}, headers=_as())
    assert wrong_code.status_code == 502
    assert api.get("/admin/dropbox", headers=_as()).json()["connected"] is False


def test_only_the_owner_manages_dropbox(api):
    assert api.get("/admin/dropbox", headers=_as(role="attorney")).status_code == 403
    assert api.post("/admin/dropbox/connect", headers=_as(role="paralegal")).status_code == 403


def test_browse_and_choose_folders(api):
    _connect(api)
    top = api.get("/admin/dropbox/folders", headers=_as()).json()
    assert top["path"] == "" and top["parent"] is None
    assert [f["name"] for f in top["folders"]] == ["Clients", "Firm Library", "Personal"]

    inside = api.get("/admin/dropbox/folders", params={"path": "/clients"}, headers=_as()).json()
    assert inside["parent"] == "" and [f["path"] for f in inside["folders"]] == ["/Clients/Diksha"]

    saved = api.put("/admin/dropbox/folders", json={"paths": ["/clients/diksha", "/Firm Library"]}, headers=_as())
    assert saved.status_code == 200
    assert saved.json()["folders"] == [
        {"path": "/Clients/Diksha", "library_folder": "Diksha"},
        {"path": "/Firm Library", "library_folder": "Firm Library"},
    ]
    marked = api.get("/admin/dropbox/folders", params={"path": "/Clients"}, headers=_as()).json()["folders"]
    assert marked == [{"name": "Diksha", "path": "/Clients/Diksha", "selected": True}]

    assert api.put("/admin/dropbox/folders", json={"paths": ["/Nope"]}, headers=_as()).status_code == 400
    assert api.put("/admin/dropbox/folders", json={"paths": [""]}, headers=_as()).status_code == 400
    nested = api.put("/admin/dropbox/folders", json={"paths": ["/Clients", "/Clients/Diksha"]}, headers=_as())
    assert nested.status_code == 400 and "inside" in nested.json()["detail"]
    # another organization sees none of it
    assert api.get("/admin/dropbox", headers=_as(tenant_id=2)).json()["connected"] is False
    assert api.get("/admin/dropbox/folders", headers=_as(tenant_id=2)).status_code == 409


def test_chosen_folders_sync_into_library_folders_and_unticking_removes_them(api, env, dropbox, _fake_vector_store):
    dropbox.files = {
        "/Clients/Diksha/overtime.txt": ("r1", b"Overtime after 8 hours a day."),
        "/Clients/Diksha/Wage/breaks.txt": ("r1", b"Meal breaks after 5 hours."),
        "/Firm Library/discovery.txt": ("r1", b"Discovery requires a noticed motion."),
        "/Personal/taxes.txt": ("r1", b"Never synced."),
    }
    _connect(api)
    api.put("/admin/dropbox/folders", json={"paths": ["/Clients/Diksha", "/Firm Library"]}, headers=_as())
    assert synced_tenant_ids(env.repo) == [1]

    run = run_vault_sync(repository=env.repo, storage_backend=env.storage, vector_store=_fake_vector_store,
                         process=False, tenant_id=1)
    assert run["status"] == "ok" and run["added"] == 3
    docs = {(d["category"], d["filename"]) for d in env.repo.list_documents(tenant_id=1)}
    assert docs == {("Diksha", "overtime.txt"), ("Diksha/Wage", "breaks.txt"), ("Firm Library", "discovery.txt")}
    assert "Dropbox (diksha@firm.com): Diksha, Firm Library" == run["source"]

    status = api.get("/admin/vault-sync", headers=_as()).json()
    assert status["configured"] is True and status["last_run"]["added"] == 3

    # untick one folder: its files leave the library on the next run
    api.put("/admin/dropbox/folders", json={"paths": ["/Clients/Diksha"]}, headers=_as())
    run = run_vault_sync(repository=env.repo, storage_backend=env.storage, vector_store=_fake_vector_store,
                         process=False, tenant_id=1)
    assert run["deleted"] == 1
    assert ("Firm Library", "discovery.txt") not in {(d["category"], d["filename"]) for d in env.repo.list_documents(tenant_id=1)}


def test_disconnect_revokes_and_keeps_the_library(api, env, dropbox, _fake_vector_store):
    dropbox.files = {"/Firm Library/discovery.txt": ("r1", b"Discovery requires a noticed motion.")}
    _connect(api)
    api.put("/admin/dropbox/folders", json={"paths": ["/Firm Library"]}, headers=_as())
    run_vault_sync(repository=env.repo, storage_backend=env.storage, vector_store=_fake_vector_store,
                   process=False, tenant_id=1)

    status = api.delete("/admin/dropbox", headers=_as()).json()
    assert status["connected"] is False and dropbox.revoked is True
    assert env.repo.get_dropbox_connection(1) is None
    assert len(env.repo.list_documents(tenant_id=1)) == 1  # the library keeps its files
    assert synced_tenant_ids(env.repo) == []
    assert api.get("/admin/vault-sync", headers=_as()).json()["configured"] is False


def test_reconnecting_the_same_account_keeps_the_folders(api):
    _connect(api)
    api.put("/admin/dropbox/folders", json={"paths": ["/Firm Library"]}, headers=_as())
    assert [f["path"] for f in _connect(api).json()["folders"]] == ["/Firm Library"]


def test_a_rotated_key_asks_the_owner_to_reconnect(api, monkeypatch):
    _connect(api)
    monkeypatch.setattr(get_settings(), "jwt_secret_key", "a-different-signing-key-" + "x" * 30)
    headers = _as()  # a token signed with the new key
    assert api.get("/admin/dropbox", headers=headers).json()["needs_reconnect"] is True
    assert api.get("/admin/dropbox/folders", headers=headers).status_code == 409


def test_library_folder_names_are_unique():
    assert folder_labels(["/A/Docs", "/B/Docs", "/C/docs"]) == {"/A/Docs": "Docs", "/B/Docs": "Docs (2)", "/C/docs": "docs (3)"}


def test_dropbox_unavailable_without_the_app_keys(api, monkeypatch):
    monkeypatch.setattr(get_settings(), "dropbox_app_key", "")
    assert api.get("/admin/dropbox", headers=_as()).json()["available"] is False
    assert api.post("/admin/dropbox/connect", headers=_as()).status_code == 409

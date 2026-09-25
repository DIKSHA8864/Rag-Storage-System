"""
Vault sync (app/vault_sync/) - Blueprint Test 6: "add, revise, and delete a
vault file -> the index reflects each change without developer action".
Real LocalStorageBackend + SQLite repository + conftest.py's in-memory
vector store; the Dropbox API is a fake HTTP session.
"""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key
from app.storage.local_backend import LocalStorageBackend
from app.vault_sync.dropbox_source import DropboxMirror
from app.vault_sync.folder_sync import SyncRefused, sync_folder


@pytest.fixture
def env(tmp_path):
    source = tmp_path / "Dropbox" / "AshiLegal Library"
    source.mkdir(parents=True)
    return SimpleNamespace(
        source=source,
        repo=SQLiteMetadataRepository(tmp_path / "metadata.db"),
        storage=LocalStorageBackend(originals_dir=tmp_path / "originals", quarantine_dir=tmp_path / "quarantine"),
        originals=tmp_path / "originals",
    )


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _sync(env, store, **kwargs):
    return sync_folder(env.source, 1, env.repo, env.storage, store, **kwargs)


def _docs(env):
    return {(d["category"], d["filename"]): d for d in env.repo.list_documents(tenant_id=1)}


def test_add_revise_and_delete_are_mirrored_into_the_library(env, _fake_vector_store):
    _write(env.source / "Harassment" / "discovery.txt", "Discovery requires a noticed motion.")
    _write(env.source / "Wage" / "Overtime" / "daily.txt", "Overtime after 8 hours a day.")
    _write(env.source / "loose note.txt", "A file at the top level.")

    result = _sync(env, _fake_vector_store)

    assert (result.added, result.updated, result.deleted) == (3, 0, 0)
    assert set(_docs(env)) == {("Harassment", "discovery.txt"), ("Wage/Overtime", "daily.txt"), ("Unfiled", "loose note.txt")}
    assert all(d["status"] == "Uploaded" for d in _docs(env).values())
    assert (env.originals / "tenant-1" / "Wage" / "Overtime" / "daily.txt").read_text() == "Overtime after 8 hours a day."

    # nothing changed -> nothing touched
    assert (_sync(env, _fake_vector_store).unchanged, _sync(env, _fake_vector_store).added) == (3, 0)

    # revise: new content replaces the library copy and its old chunks leave search immediately
    _fake_vector_store.upsert_chunk_embedding(
        chunk_id="old-1", document_id="d", category="Harassment", filename="discovery.txt",
        chunk_text="OLD TEXT", embedding=[0.0] * 384, model_name="t", tenant_id=1,
    )
    _write(env.source / "Harassment" / "discovery.txt", "Discovery requires a noticed motion and a declaration.")
    result = _sync(env, _fake_vector_store)
    assert result.updated == 1
    assert "old-1" not in _fake_vector_store._rows
    assert (env.originals / "tenant-1" / "Harassment" / "discovery.txt").read_text().endswith("and a declaration.")

    # delete
    os.remove(env.source / "loose note.txt")
    result = _sync(env, _fake_vector_store)
    assert result.deleted == 1
    assert ("Unfiled", "loose note.txt") not in _docs(env)
    assert not (env.originals / "tenant-1" / "Unfiled" / "loose note.txt").exists()


def test_files_uploaded_by_hand_are_never_changed_or_deleted(env, _fake_vector_store):
    env.repo.upsert_document("Harassment", "manual.txt", ".txt", 5, "abc", tenant_id=1)
    _write(env.source / "Harassment" / "manual.txt", "A different file with the same name in Dropbox.")
    _write(env.source / "Harassment" / "synced.txt", "Synced.")

    result = _sync(env, _fake_vector_store)

    assert result.added == 1
    assert result.skipped[0]["path"] == "Harassment/manual.txt"
    assert "uploaded by hand" in result.skipped[0]["reason"]
    assert _docs(env)[("Harassment", "manual.txt")]["sha256"] == "abc"

    os.remove(env.source / "Harassment" / "manual.txt")
    os.remove(env.source / "Harassment" / "synced.txt")
    _write(env.source / "Harassment" / "other.txt", "keeps the folder non-empty")
    _sync(env, _fake_vector_store)
    assert ("Harassment", "manual.txt") in _docs(env)  # never managed by sync -> never deleted
    assert ("Harassment", "synced.txt") not in _docs(env)


def test_temporary_hidden_unsupported_and_duplicate_files_are_skipped(env, _fake_vector_store):
    _write(env.source / "Harassment" / "memo.txt", "Same content.")
    _write(env.source / "Archive" / "memo copy.txt", "Same content.")
    _write(env.source / "Harassment" / "~$memo.docx", "office lock file")
    _write(env.source / "Harassment" / "draft.txt.part", "partial download")
    _write(env.source / ".dropbox.cache" / "x.txt", "cache")
    _write(env.source / "Harassment" / "photo.png", "not a library format")

    result = _sync(env, _fake_vector_store)

    assert result.added == 1
    reasons = {s["path"]: s["reason"] for s in result.skipped}
    # files are synced in path order, so the Archive copy lands first and the second is the duplicate
    assert reasons["Harassment/memo.txt"] == "same content is already in the library as 'Archive/memo copy.txt'"
    assert reasons["Harassment/photo.png"].startswith("unsupported_extension")
    assert not any("~$" in p or ".part" in p or ".dropbox" in p for p in reasons)


def test_a_missing_or_suddenly_empty_folder_never_wipes_the_library(env, _fake_vector_store, tmp_path):
    for i in range(3):
        _write(env.source / "Docs" / f"{i}.txt", f"doc {i}")
    _sync(env, _fake_vector_store)

    with pytest.raises(SyncRefused, match="doesn't exist"):
        sync_folder(tmp_path / "not-mounted", 1, env.repo, env.storage, _fake_vector_store)

    for i in range(3):
        os.remove(env.source / "Docs" / f"{i}.txt")
    with pytest.raises(SyncRefused, match="is empty"):
        _sync(env, _fake_vector_store)
    assert len(_docs(env)) == 3


def test_mass_deletion_needs_explicit_permission(env, _fake_vector_store):
    for i in range(12):
        _write(env.source / "Docs" / f"{i}.txt", f"doc {i}")
    _write(env.source / "Keep" / "keep.txt", "stays")
    _sync(env, _fake_vector_store)
    for i in range(12):
        os.remove(env.source / "Docs" / f"{i}.txt")

    with pytest.raises(SyncRefused, match="disappeared"):
        _sync(env, _fake_vector_store)
    assert len(_docs(env)) == 13

    assert _sync(env, _fake_vector_store, allow_mass_delete=True).deleted == 12


# ---------------------------------------------------------------------
# Runner: sync -> index -> recorded run
# ---------------------------------------------------------------------


class _HashEmbedder:
    def embed(self, texts):
        return [[b / 255 for b in (hashlib.sha256(t.encode()).digest() * 12)] for t in texts]


@pytest.fixture
def pipeline_dirs(tmp_path, monkeypatch, env):
    from app.embeddings import embedding_manager
    from app.extraction import extractor_manager
    from app.segmentation import chunker, segmentation_manager

    monkeypatch.setattr(extractor_manager, "ORIGINALS_DIR", env.originals)
    for module, attr, name in [
        (extractor_manager, "PROCESSED_DIR", "processed"), (segmentation_manager, "PROCESSED_DIR", "processed"),
        (segmentation_manager, "SEGMENTS_DIR", "segments"), (chunker, "SEGMENTS_DIR", "segments"),
        (chunker, "CHUNKS_DIR", "chunks"), (embedding_manager, "CHUNKS_DIR", "chunks"),
        (embedding_manager, "EMBEDDINGS_DIR", "embeddings"),
    ]:
        monkeypatch.setattr(module, attr, tmp_path / name)
    monkeypatch.setattr(embedding_manager, "get_embedding_provider", lambda model_name=None: _HashEmbedder())


def _settings(monkeypatch, **values):
    from config.settings import get_settings

    settings = get_settings()
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    return settings


def test_a_run_syncs_indexes_and_is_recorded(env, pipeline_dirs, _fake_vector_store, monkeypatch):
    from app.vault_sync.runner import run_vault_sync

    _settings(monkeypatch, vault_sync_dir=str(env.source), vault_sync_tenant_id=1, dropbox_refresh_token="")
    _write(env.source / "Harassment" / "discovery.txt", "Discovery of sexual conduct requires a noticed motion.")

    run = run_vault_sync(env.repo, env.storage, _fake_vector_store)

    assert run["status"] == "ok" and run["added"] == 1
    assert run["processing"]["embeddings_created"] >= 1
    assert _docs(env)[("Harassment", "discovery.txt")]["status"] == "Indexed"
    assert any(r["filename"] == "discovery.txt" for r in _fake_vector_store._rows.values())
    assert env.repo.latest_vault_sync_run(1)["added"] == 1

    os.remove(env.source / "Harassment" / "discovery.txt")
    _write(env.source / "Other" / "x.txt", "something else entirely")
    run_vault_sync(env.repo, env.storage, _fake_vector_store)
    assert not any(r["filename"] == "discovery.txt" for r in _fake_vector_store._rows.values())


def test_a_refused_run_is_recorded_with_its_reason(env, _fake_vector_store, monkeypatch, tmp_path):
    from app.vault_sync.runner import run_vault_sync

    _settings(monkeypatch, vault_sync_dir=str(tmp_path / "not-mounted"), vault_sync_tenant_id=1)

    run = run_vault_sync(env.repo, env.storage, _fake_vector_store)

    assert run["status"] == "refused"
    last = env.repo.latest_vault_sync_run(1)
    assert last["status"] == "refused" and "doesn't exist" in last["error"]


# ---------------------------------------------------------------------
# Dropbox API mirror (fake HTTP)
# ---------------------------------------------------------------------


class _Response:
    def __init__(self, body=None, content=b""):
        self._body, self.content, self.status_code, self.text = body, content, 200, ""

    def json(self):
        return self._body


class _FakeDropbox:
    """Dropbox HTTP API v2 stand-in: token refresh, paged list_folder, download."""

    def __init__(self):
        self.files = {}  # path_display -> (rev, bytes)
        self.downloads = []
        self._remaining = []

    def post(self, url, json=None, data=None, headers=None, auth=None, timeout=None):
        import json as jsonlib

        if url.endswith("/oauth2/token"):
            assert data["grant_type"] == "refresh_token" and auth == ("key", "secret")
            return _Response({"access_token": "tok", "expires_in": 14400})
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/files/list_folder"):
            assert json == {"path": "/Library", "recursive": True, "include_deleted": False}
            entries = [{".tag": "folder", "path_display": "/Library/Harassment"}] + [
                {".tag": "file", "path_display": p, "path_lower": p.lower(), "rev": rev}
                for p, (rev, _) in self.files.items()
            ]
            self._remaining = entries[2:]  # force a second page
            return _Response({"entries": entries[:2], "cursor": "c1", "has_more": bool(self._remaining)})
        if url.endswith("/list_folder/continue"):
            return _Response({"entries": self._remaining, "cursor": "c2", "has_more": False})
        if url.endswith("/files/download"):
            path = jsonlib.loads(headers["Dropbox-API-Arg"])["path"]
            display = next(p for p in self.files if p.lower() == path)
            self.downloads.append(display)
            return _Response(content=self.files[display][1])
        raise AssertionError(url)


def test_dropbox_mirror_downloads_changes_only_and_removes_deleted_files(tmp_path):
    fake = _FakeDropbox()
    fake.files = {
        "/Library/Harassment/discovery.pdf": ("r1", b"v1"),
        "/Library/Wage/overtime.docx": ("r1", b"ot"),
    }
    mirror = DropboxMirror("key", "secret", "refresh", "/Library", tmp_path / "mirror", session=fake)

    assert mirror.refresh() == {"downloaded": 2, "removed": 0, "unchanged": 0}
    assert (tmp_path / "mirror" / "Harassment" / "discovery.pdf").read_bytes() == b"v1"

    fake.files["/Library/Harassment/discovery.pdf"] = ("r2", b"v2")
    del fake.files["/Library/Wage/overtime.docx"]
    fake.downloads.clear()

    assert mirror.refresh() == {"downloaded": 1, "removed": 1, "unchanged": 0}
    assert fake.downloads == ["/Library/Harassment/discovery.pdf"]
    assert (tmp_path / "mirror" / "Harassment" / "discovery.pdf").read_bytes() == b"v2"
    assert not (tmp_path / "mirror" / "Wage" / "overtime.docx").exists()
    assert json.loads((tmp_path / "mirror" / ".dropbox_index.json").read_text()) == {"Harassment/discovery.pdf": "r2"}


# ---------------------------------------------------------------------
# API + duplicate uploads
# ---------------------------------------------------------------------


@pytest.fixture
def api(env, monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", env.repo)
    monkeypatch.setattr(storage_api, "storage_backend", env.storage)
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _owner(tenant_id=1, role="owner"):
    token = create_access_token(owner_id=1, email="o@firm.com", tenant_id=tenant_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def test_sync_now_runs_and_the_status_shows_the_last_run(api, env, pipeline_dirs, monkeypatch):
    _settings(monkeypatch, vault_sync_dir=str(env.source), vault_sync_tenant_id=1, dropbox_refresh_token="")
    _write(env.source / "Harassment" / "discovery.txt", "Discovery requires a noticed motion.")

    started = api.post("/admin/vault-sync/run", headers=_owner())
    assert started.status_code == 200

    status = api.get("/admin/vault-sync", headers=_owner()).json()
    assert status["configured"] is True and status["source"] == f"Folder {env.source}"
    assert status["last_run"]["status"] == "ok" and status["last_run"]["added"] == 1

    # another organization (and a non-owner) can't see or trigger it
    assert api.get("/admin/vault-sync", headers=_owner(tenant_id=2)).json()["configured"] is False
    assert api.post("/admin/vault-sync/run", headers=_owner(tenant_id=2)).status_code == 409
    assert api.post("/admin/vault-sync/run", headers=_owner(role="paralegal")).status_code == 403


def test_uploading_the_same_content_twice_is_rejected_as_a_duplicate(api):
    def upload(category, name):
        return api.post(
            f"/categories/{category}/documents/batch",
            files=[("files", (name, b"Identical library text.", "text/plain"))],
            headers=_owner(),
        ).json()["results"][0]

    assert upload("Harassment", "memo.txt")["status"] == "stored"
    second = upload("Archive", "memo (copy).txt")

    assert second["status"] == "rejected"
    assert second["reason"].startswith("duplicate of Harassment/memo.txt")

"""
Tests for Matters (isolated End User identities, app/metadata/base.py,
app/security/auth.py) and Threads (conversation history scoped to a
Matter, app/api/end_user_api.py's /end-user/threads* and
/end-user/query/stream).

Two client fixtures, same split as tests/test_auth.py:
- `client` (bypassed auth, like every other non-auth test file) for
  the repository contract and the Owner-side /admin/matters endpoints.
- `real_auth_client` (auth NOT bypassed) for anything that needs to
  prove isolation actually works across two different X-End-User-Key
  values - bypassing auth there would make the isolation assertion
  meaningless.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api import end_user_api, storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, hash_api_key, require_admin_key, require_end_user_key
from app.storage.local_backend import LocalStorageBackend
from config.settings import get_settings


# ---------------------------------------------------------------------
# Repository contract (SQLiteMetadataRepository) - Matters
# ---------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


def test_get_matter_by_key_hash_returns_none_for_unknown_hash(repo):
    assert repo.get_matter_by_key_hash(hash_api_key("nope")) is None


def test_create_matter_then_resolve_by_key_hash(repo):
    created = repo.create_matter("Acme Corp", hash_api_key("secret-key-123"))
    assert created["name"] == "Acme Corp"

    resolved = repo.get_matter_by_key_hash(hash_api_key("secret-key-123"))
    assert resolved["id"] == created["id"]
    assert resolved["name"] == "Acme Corp"


def test_list_matters_returns_every_matter(repo):
    repo.create_matter("Acme Corp", hash_api_key("key-a"))
    repo.create_matter("Beta LLC", hash_api_key("key-b"))

    names = {m["name"] for m in repo.list_matters()}
    assert names == {"Acme Corp", "Beta LLC"}


# ---------------------------------------------------------------------
# Repository contract - Threads
# ---------------------------------------------------------------------


def test_create_thread_then_list(repo):
    matter = repo.create_matter("Acme Corp", hash_api_key("key-a"))
    repo.create_thread(matter["id"], "First question")

    threads = repo.list_threads(matter["id"])
    assert len(threads) == 1
    assert threads[0]["title"] == "First question"


def test_get_thread_returns_none_for_a_different_matter(repo):
    matter_a = repo.create_matter("Acme Corp", hash_api_key("key-a"))
    matter_b = repo.create_matter("Beta LLC", hash_api_key("key-b"))
    thread = repo.create_thread(matter_a["id"], "Acme's thread")

    assert repo.get_thread(thread["id"], matter_a["id"]) is not None
    assert repo.get_thread(thread["id"], matter_b["id"]) is None


def test_add_thread_message_then_list(repo):
    matter = repo.create_matter("Acme Corp", hash_api_key("key-a"))
    thread = repo.create_thread(matter["id"], "Q&A")

    repo.add_thread_message(thread["id"], "user", "What is the policy?")
    repo.add_thread_message(thread["id"], "assistant", "The policy is...", json.dumps([{"filename": "a.pdf"}]))

    messages = repo.list_thread_messages(thread["id"])
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert json.loads(messages[1]["sources_json"]) == [{"filename": "a.pdf"}]


# ---------------------------------------------------------------------
# Owner-side /admin/matters (bypassed auth, like every other
# non-auth endpoint test file)
# ---------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    backend = LocalStorageBackend(
        originals_dir=tmp_path / "originals",
        quarantine_dir=tmp_path / "quarantine",
    )
    repository = SQLiteMetadataRepository(tmp_path / "metadata.db")

    monkeypatch.setattr(storage_api, "storage_backend", backend)
    monkeypatch.setattr(storage_api, "metadata_repository", repository)

    return TestClient(storage_api.app)


def test_create_matter_returns_plaintext_key_once(client):
    response = client.post("/admin/matters", json={"name": "Acme Corp"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Acme Corp"
    assert len(body["api_key"]) > 20


def test_list_matters_never_exposes_the_api_key(client):
    client.post("/admin/matters", json={"name": "Acme Corp"})

    response = client.get("/admin/matters")
    assert response.status_code == 200
    matters = response.json()["matters"]
    assert len(matters) == 1
    assert "api_key" not in matters[0]
    assert "api_key_hash" not in matters[0]


# ---------------------------------------------------------------------
# End User side: real auth (not bypassed) - proves isolation across
# two different X-End-User-Key values.
# ---------------------------------------------------------------------


@pytest.fixture
def real_auth_client(tmp_path, monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)

    monkeypatch.setattr(
        storage_api,
        "storage_backend",
        LocalStorageBackend(
            originals_dir=tmp_path / "originals",
            quarantine_dir=tmp_path / "quarantine",
        ),
    )
    monkeypatch.setattr(
        storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db")
    )
    monkeypatch.setattr(end_user_api, "retrieve", lambda *args, **kwargs: [])

    yield TestClient(storage_api.app)

    storage_api.app.dependency_overrides[require_admin_key] = lambda: None
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: None


def _create_matter(client, name):
    owner_token = create_access_token(owner_id=1, email="owner@example.com")
    response = client.post(
        "/admin/matters", json={"name": name}, headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert response.status_code == 200
    return response.json()


def test_create_thread_rejects_missing_key(real_auth_client):
    response = real_auth_client.post("/end-user/threads", json={"title": "Hi"})
    assert response.status_code == 401


def test_create_thread_resolves_the_calling_matter(real_auth_client):
    matter = _create_matter(real_auth_client, "Acme Corp")

    response = real_auth_client.post(
        "/end-user/threads",
        json={"title": "Vendor question"},
        headers={"X-End-User-Key": matter["api_key"]},
    )

    assert response.status_code == 200
    assert response.json()["matter_id"] == matter["id"]


def test_legacy_shared_key_resolves_to_default_matter(real_auth_client):
    legacy_key = get_settings().end_user_api_key

    response = real_auth_client.post(
        "/end-user/threads", json={"title": "Hi"}, headers={"X-End-User-Key": legacy_key}
    )

    assert response.status_code == 200
    assert response.json()["matter_id"] == 0


def test_matters_cannot_see_each_others_threads(real_auth_client):
    matter_a = _create_matter(real_auth_client, "Acme Corp")
    matter_b = _create_matter(real_auth_client, "Beta LLC")

    created = real_auth_client.post(
        "/end-user/threads",
        json={"title": "Acme's thread"},
        headers={"X-End-User-Key": matter_a["api_key"]},
    ).json()

    # Matter B's own thread list is empty - Acme's thread isn't in it.
    list_response = real_auth_client.get(
        "/end-user/threads", headers={"X-End-User-Key": matter_b["api_key"]}
    )
    assert list_response.json()["threads"] == []

    # Matter B can't read Acme's thread's messages by id either.
    messages_response = real_auth_client.get(
        f"/end-user/threads/{created['id']}/messages",
        headers={"X-End-User-Key": matter_b["api_key"]},
    )
    assert messages_response.status_code == 404

    # Matter A can read its own thread just fine.
    own_response = real_auth_client.get(
        f"/end-user/threads/{created['id']}/messages",
        headers={"X-End-User-Key": matter_a["api_key"]},
    )
    assert own_response.status_code == 200


# ---------------------------------------------------------------------
# POST /end-user/query/stream + thread persistence (bypassed-auth
# client - _current_matter() falls back to the Default matter, id=0,
# which is sufficient to test persistence; isolation itself is
# covered above against real, distinct Matters).
# ---------------------------------------------------------------------


def _hit(score=0.9):
    return {
        "chunk_id": "c-1",
        "document_id": "policy",
        "category": "Docs",
        "filename": "policy.pdf",
        "chunk_text": "Vendor contracts require annual review.",
        "chapter": None,
        "section": "1.1",
        "start_page": 1,
        "end_page": 1,
        "metadata": {},
        "vector_score": score,
        "keyword_score": 0.0,
        "final_score": score,
    }


def test_stream_with_thread_id_persists_both_turns(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    thread = client.post("/end-user/threads", json={"title": "Vendor Qs"}).json()

    with client.stream(
        "POST",
        "/end-user/query/stream",
        json={"query": "What is the vendor policy?", "thread_id": thread["id"]},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: sources" in body
    assert "event: done" in body

    messages = client.get(f"/end-user/threads/{thread['id']}/messages").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is the vendor policy?"
    assert messages[1]["sources"][0]["filename"] == "policy.pdf"


def test_stream_without_thread_id_persists_nothing(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    thread = client.post("/end-user/threads", json={"title": "Untouched"}).json()

    with client.stream("POST", "/end-user/query/stream", json={"query": "hello"}) as response:
        "".join(response.iter_text())

    messages = client.get(f"/end-user/threads/{thread['id']}/messages").json()["messages"]
    assert messages == []


def test_stream_rejects_a_thread_id_from_a_different_matter(real_auth_client):
    matter_a = _create_matter(real_auth_client, "Acme Corp")
    matter_b = _create_matter(real_auth_client, "Beta LLC")

    thread = real_auth_client.post(
        "/end-user/threads",
        json={"title": "Acme's thread"},
        headers={"X-End-User-Key": matter_a["api_key"]},
    ).json()

    with real_auth_client.stream(
        "POST",
        "/end-user/query/stream",
        json={"query": "hello", "thread_id": thread["id"]},
        headers={"X-End-User-Key": matter_b["api_key"]},
    ) as response:
        body = "".join(response.iter_text())

    assert "event: error" in body
    assert "Thread not found" in body

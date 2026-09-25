"""
One matter per case (migration 0024): every intake a signed-in client
starts opens its own case matter, and attorneys upload that case's
documents (pleadings, orders...) into it - indexed only into that
matter's namespace. Access-code callers and intakes started before
this keep working in their existing matter.
"""

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import require_admin_key, require_end_user_key
from app.storage.local_backend import LocalStorageBackend
from tests.conftest import _FakeQueue


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(tmp_path, monkeypatch, repo):
    import app.api.intake_api as intake_api
    import app.api.matter_documents_api as matter_documents_api
    import app.storage as storage_module

    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    backend = LocalStorageBackend(originals_dir=tmp_path / "intake", quarantine_dir=tmp_path / "intake_quarantine")
    monkeypatch.setattr(storage_module, "get_intake_storage_backend", lambda: backend)
    monkeypatch.setattr(intake_api, "get_job_queue", lambda: _FakeQueue())
    monkeypatch.setattr(matter_documents_api, "get_job_queue", lambda: _FakeQueue())
    monkeypatch.setattr(
        "app.matter_rag.ingestion.process_submission",
        lambda filename, data: [
            {"chunk_index": i, "text": part, "embedding": [0.1] * 384}
            for i, part in enumerate(data.decode().split("\n\n")) if part.strip()
        ],
    )
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: None


def _client_account(repo, email: str, tenant_id: int = 1) -> dict:
    """A signed-in client exactly as require_end_user_key resolves one: their personal matter + account id."""

    import uuid

    personal = repo.create_matter(f"Client {email}", uuid.uuid4().hex, tenant_id=tenant_id)
    invite = repo.create_end_user_invite(email, tenant_id, "owner@example.com")
    repo.activate_end_user(invite["id"], "hash", personal["id"], datetime.now(timezone.utc).isoformat())
    return {"id": personal["id"], "name": personal["name"], "tenant_id": tenant_id, "end_user_id": invite["id"]}


def _sign_in(identity: dict) -> None:
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: identity


def test_each_intake_opens_its_own_case_matter(client, repo):
    alice = _client_account(repo, "alice@example.com")
    _sign_in(alice)

    first = client.post("/end-user/intake/sessions", json={"title": "Unpaid overtime"}).json()
    second = client.post("/end-user/intake/sessions", json={"title": "Wrongful termination"}).json()

    assert first["matter_id"] != second["matter_id"] != alice["id"]
    case = repo.get_matter(first["matter_id"])
    assert (case["kind"], case["end_user_id"], case["tenant_id"]) == ("case", alice["end_user_id"], 1)
    assert case["name"] == "Unpaid overtime (alice@example.com)"
    listed = client.get("/end-user/intake/sessions").json()["sessions"]
    assert {s["id"] for s in listed} == {first["id"], second["id"]}

    # Everything else about the session works through the case matter.
    upload = client.post(
        f"/end-user/intake/sessions/{first['id']}/uploads",
        files={"file": ("notes.txt", io.BytesIO(b"I was not paid overtime."), "text/plain")},
    )
    assert upload.status_code == 200
    assert repo.get_uploaded_input(upload.json()["uploaded_input"]["id"])["matter_id"] == first["matter_id"]
    assert client.post(f"/end-user/intake/sessions/{first['id']}/interview/start").status_code == 200


def test_clients_cannot_reach_each_others_cases(client, repo):
    alice = _client_account(repo, "alice@example.com")
    bob = _client_account(repo, "bob@example.com")
    _sign_in(alice)
    alice_session = client.post("/end-user/intake/sessions", json={"title": "Alice case"}).json()

    _sign_in(bob)
    assert client.get(f"/end-user/intake/sessions/{alice_session['id']}").status_code == 404
    assert client.post(f"/end-user/intake/sessions/{alice_session['id']}/interview/start").status_code == 404
    assert client.get("/end-user/intake/sessions").json()["sessions"] == []


def test_intakes_started_before_case_matters_stay_reachable(client, repo):
    alice = _client_account(repo, "alice@example.com")
    old = repo.create_intake_session(alice["id"], "Older intake")
    _sign_in(alice)

    assert client.get(f"/end-user/intake/sessions/{old['id']}").status_code == 200
    assert old["id"] in {s["id"] for s in client.get("/end-user/intake/sessions").json()["sessions"]}


def test_access_code_callers_keep_one_matter(client, repo):
    storage_api.app.dependency_overrides[require_end_user_key] = lambda: None  # the implicit Default matter

    session = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()

    assert session["matter_id"] == 0


def test_matter_limit_files_the_intake_under_the_clients_own_matter(client, repo, monkeypatch):
    from app.billing.service import BillingService, PlanLimitExceededError

    def full(self, tenant_id, resource, requested_increment=1):
        raise PlanLimitExceededError(resource, 3, 4)

    monkeypatch.setattr(BillingService, "check_limit", full)
    alice = _client_account(repo, "alice@example.com")
    _sign_in(alice)

    session = client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()

    assert session["matter_id"] == alice["id"]


def test_admin_sees_case_matters_with_the_client(client, repo):
    alice = _client_account(repo, "alice@example.com")
    _sign_in(alice)
    session = client.post("/end-user/intake/sessions", json={"title": "Overtime"}).json()

    matters = {m["id"]: m for m in client.get("/admin/matters").json()["matters"]}

    assert matters[session["matter_id"]]["kind"] == "case"
    assert matters[session["matter_id"]]["client_email"] == "alice@example.com"
    assert matters[alice["id"]]["kind"] == "client"
    assert matters[alice["id"]]["client_email"] == "alice@example.com"
    detail = client.get(f"/admin/matters/{session['matter_id']}").json()
    assert (detail["kind"], detail["client_email"]) == ("case", "alice@example.com")


# ----------------------------------------------------------------------
# Attorney case documents
# ----------------------------------------------------------------------

PLEADING = b"COMPLAINT FOR DAMAGES\n\nFirst cause of action: failure to pay overtime.\n\nPrayer for relief."


def _case(client, repo) -> int:
    _sign_in(_client_account(repo, "alice@example.com"))
    return client.post("/end-user/intake/sessions", json={"title": "Overtime"}).json()["matter_id"]


def _upload(client, matter_id, name="complaint.txt", content=PLEADING, doc_type="pleading"):
    return client.post(
        f"/admin/matters/{matter_id}/documents",
        files={"file": (name, io.BytesIO(content), "text/plain")}, data={"doc_type": doc_type},
    )


def test_case_document_is_indexed_into_its_matter_only(client, repo, _fake_vector_store):
    matter_id = _case(client, repo)

    response = _upload(client, matter_id)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["chunk_count"], body["doc_type"]) == ("indexed", 3, "pleading")
    rows = list(_fake_vector_store._rows.values())
    assert {r["category"] for r in rows} == {f"matter-{matter_id}"}
    assert {r["document_id"] for r in rows} == {f"matter-{matter_id}:case-{body['id']}"}

    listed = client.get(f"/admin/matters/{matter_id}/documents").json()
    assert [d["original_filename"] for d in listed["documents"]] == ["complaint.txt"]
    assert "order" in listed["doc_types"]

    download = client.get(f"/admin/matters/{matter_id}/documents/{body['id']}/download")
    assert download.content == PLEADING
    assert 'filename="complaint.txt"' in download.headers["content-disposition"]


def test_case_document_rules(client, repo):
    matter_id = _case(client, repo)
    _upload(client, matter_id)

    assert _upload(client, matter_id, name="copy.txt").status_code == 409  # same content twice
    assert _upload(client, matter_id, name="x.txt", content=b"other", doc_type="memo").status_code == 400
    assert _upload(client, matter_id, name="x.exe", content=b"MZ").status_code == 400
    assert _upload(client, 9999, content=b"other").status_code == 404


def test_deleting_a_case_document_removes_its_chunks(client, repo, _fake_vector_store):
    matter_id = _case(client, repo)
    keep = _upload(client, matter_id, name="order.txt", content=b"ORDER granting motion.", doc_type="order").json()
    doomed = _upload(client, matter_id).json()

    assert client.delete(f"/admin/matters/{matter_id}/documents/{doomed['id']}").json() == {"deleted": True}

    assert {r["document_id"] for r in _fake_vector_store._rows.values()} == {f"matter-{matter_id}:case-{keep['id']}"}
    assert [d["id"] for d in client.get(f"/admin/matters/{matter_id}/documents").json()["documents"]] == [keep["id"]]
    assert client.get(f"/admin/matters/{matter_id}/documents/{doomed['id']}/download").status_code == 404


def test_unreadable_document_is_marked_failed_and_can_be_reindexed(client, repo, monkeypatch):
    matter_id = _case(client, repo)
    monkeypatch.setattr("app.matter_rag.ingestion.process_submission", lambda filename, data: [])

    failed = _upload(client, matter_id).json()
    assert failed["status"] == "failed" and "No text" in failed["error"]

    monkeypatch.setattr(
        "app.matter_rag.ingestion.process_submission",
        lambda filename, data: [{"chunk_index": 0, "text": "text", "embedding": [0.1] * 384}],
    )
    again = client.post(f"/admin/matters/{matter_id}/documents/{failed['id']}/reindex").json()
    assert (again["status"], again["chunk_count"], again["error"]) == ("indexed", 1, None)


def test_case_documents_follow_matter_access(client, repo):
    matter_id = _case(client, repo)
    _upload(client, matter_id)

    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "42", "email": "attorney@example.com", "role": "attorney", "tenant_id": 1,
    }
    try:
        assert client.get(f"/admin/matters/{matter_id}/documents").status_code == 403
        repo.create_matter_assignment(42, matter_id, "attorney")
        assert client.get(f"/admin/matters/{matter_id}/documents").status_code == 200
    finally:
        storage_api.app.dependency_overrides.pop(require_admin_key, None)

    storage_api.app.dependency_overrides[require_admin_key] = lambda: {
        "sub": "7", "email": "other-firm@example.com", "role": "owner", "tenant_id": 2,
    }
    try:
        assert client.get(f"/admin/matters/{matter_id}/documents").status_code == 404
    finally:
        storage_api.app.dependency_overrides.pop(require_admin_key, None)

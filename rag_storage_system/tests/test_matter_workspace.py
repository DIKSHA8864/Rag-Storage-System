"""
Tests for the Matter Workspace: direct Matter<->uploaded_inputs/reports
links, and role-based access to a Matter's reports for attorney/
paralegal-role Owner accounts (app/security/auth.py's ensure_matter_access()).
"""

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def client(monkeypatch, repo):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def _owner_header(owner_id=1, role="owner"):
    token = create_access_token(owner_id=owner_id, email=f"user{owner_id}@example.com", role=role)
    return {"Authorization": f"Bearer {token}"}


def test_uploaded_input_and_report_carry_matter_id_directly(repo):
    session = repo.create_intake_session(matter_id=7, title="Intake")
    uploaded = repo.create_uploaded_input(
        intake_session_id=session["id"], matter_id=7, original_filename="a.txt",
        stored_category="c", stored_filename="a.txt", media_type="document", size=1, sha256=None,
    )
    report = repo.create_report(session["id"], 7, "docx", "c/reports", "r.docx")

    assert uploaded["matter_id"] == 7
    assert report["matter_id"] == 7


def test_attorney_role_can_authenticate_but_cannot_act_on_unassigned_matter(client, repo):
    matter = repo.create_matter("Acme Corp", "hash-1")
    session = repo.create_intake_session(matter_id=matter["id"], title="Intake")
    report = repo.create_report(session["id"], matter["id"], "docx", "c/reports", "r.docx")
    repo.create_report_review(report["id"])

    response = client.post(f"/admin/reports/{report['id']}/approve", headers=_owner_header(owner_id=5, role="attorney"))
    assert response.status_code == 403


def test_attorney_assigned_to_the_matter_can_approve_its_report(client, repo):
    matter = repo.create_matter("Acme Corp", "hash-2")
    session = repo.create_intake_session(matter_id=matter["id"], title="Intake")
    report = repo.create_report(session["id"], matter["id"], "docx", "c/reports", "r.docx")
    repo.create_report_review(report["id"])
    repo.create_matter_assignment(owner_id=5, matter_id=matter["id"], role="attorney")

    response = client.post(f"/admin/reports/{report['id']}/approve", headers=_owner_header(owner_id=5, role="attorney"))
    assert response.status_code == 200


def test_owner_role_can_act_on_any_matter_without_an_assignment(client, repo):
    matter = repo.create_matter("Acme Corp", "hash-3")
    session = repo.create_intake_session(matter_id=matter["id"], title="Intake")
    report = repo.create_report(session["id"], matter["id"], "docx", "c/reports", "r.docx")
    repo.create_report_review(report["id"])

    response = client.post(f"/admin/reports/{report['id']}/approve", headers=_owner_header(owner_id=1, role="owner"))
    assert response.status_code == 200


def test_only_owner_role_may_create_matter_assignments(client, repo):
    response = client.post(
        "/admin/matters/1/assignments", json={"owner_id": 5, "role": "attorney"},
        headers=_owner_header(owner_id=5, role="attorney"),
    )
    assert response.status_code == 403
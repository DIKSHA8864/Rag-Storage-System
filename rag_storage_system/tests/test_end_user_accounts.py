"""
Individual end-user accounts (app/security/end_user_accounts.py,
app/api/users_api.py, app/api/end_user_auth_api.py): Owner invites an
email, the user signs up once with an emailed one-time code and their
own password, then logs in with email + password. Deactivation cuts
off every existing session immediately.

Real auth throughout (the conftest bypass is removed) - bypassing it
would make every assertion here meaningless. Outbound email is
captured by a fake sender, which is how the tests read the codes.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key, require_end_user_key
from app.security.rate_limit import limiter


class _CapturingEmailSender:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.sent.append({"to": to_email, "subject": subject, "body": body})

    def latest_code_for(self, email: str) -> str:
        for message in reversed(self.sent):
            if message["to"] == email:
                match = re.search(r"\b(\d{6})\b", message["subject"])
                if match:
                    return match.group(1)
        raise AssertionError(f"No code was emailed to {email}")


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


@pytest.fixture
def mailbox(monkeypatch):
    sender = _CapturingEmailSender()
    monkeypatch.setattr("app.notifications.email_sender.get_email_sender", lambda: sender)
    return sender


@pytest.fixture
def client(repo, mailbox, monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    limiter.reset()

    yield TestClient(storage_api.app)

    limiter.reset()
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    storage_api.app.dependency_overrides.pop(require_end_user_key, None)


def _admin(tenant_id: int = 1, role: str = "owner") -> dict:
    token = create_access_token(owner_id=1, email=f"admin{tenant_id}@example.com", tenant_id=tenant_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _invite(client, *emails, tenant_id: int = 1):
    response = client.post("/admin/users", json={"emails": list(emails)}, headers=_admin(tenant_id))
    assert response.status_code == 200, response.text
    return response.json()


def _sign_up(client, mailbox, email: str, password: str = "correct-horse-1") -> str:
    assert client.post("/end-user/auth/signup/request-code", json={"email": email}).status_code == 200
    code = mailbox.latest_code_for(email)
    response = client.post(
        "/end-user/auth/signup/complete", json={"email": email, "code": code, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# ---------------------------------------------------------------------
# Owner/Admin user management
# ---------------------------------------------------------------------


def test_owner_invites_users_and_sees_them_listed(client, mailbox):
    body = _invite(client, "Rahul.AshiLegal@gmail.com", "priya.ashilegal@gmail.com")

    assert {u["email"] for u in body["invited"]} == {"rahul.ashilegal@gmail.com", "priya.ashilegal@gmail.com"}
    assert all(u["status"] == "invited" for u in body["invited"])
    assert {m["to"] for m in mailbox.sent} == {"rahul.ashilegal@gmail.com", "priya.ashilegal@gmail.com"}

    listed = client.get("/admin/users", headers=_admin()).json()["users"]
    assert [u["email"] for u in listed] == ["priya.ashilegal@gmail.com", "rahul.ashilegal@gmail.com"]


def test_inviting_an_existing_email_is_skipped_not_duplicated(client):
    _invite(client, "rahul@example.com")
    body = _invite(client, "RAHUL@example.com")

    assert body["invited"] == []
    assert body["skipped"] == [{"email": "rahul@example.com", "reason": "already invited"}]


def test_attorney_role_cannot_manage_users(client):
    response = client.post("/admin/users", json={"emails": ["x@example.com"]}, headers=_admin(role="attorney"))
    assert response.status_code == 403


def test_admin_cannot_see_or_touch_another_tenants_users(client):
    _invite(client, "tenant1user@example.com", tenant_id=1)
    user_id = client.get("/admin/users", headers=_admin(1)).json()["users"][0]["id"]

    assert client.get("/admin/users", headers=_admin(2)).json()["users"] == []
    assert client.post(f"/admin/users/{user_id}/deactivate", headers=_admin(2)).status_code == 404


# ---------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------


def test_uninvited_email_gets_the_same_response_but_no_code(client, mailbox):
    response = client.post("/end-user/auth/signup/request-code", json={"email": "stranger@example.com"})

    assert response.status_code == 200
    assert mailbox.sent == []


def test_invited_user_signs_up_and_is_signed_in(client, mailbox, repo):
    _invite(client, "rahul@example.com")
    token = _sign_up(client, mailbox, "rahul@example.com")

    me = client.get("/end-user/auth/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == "rahul@example.com"
    assert me.json()["status"] == "active"

    account = repo.get_end_user_by_email("rahul@example.com")
    assert account["matter_id"] is not None
    assert repo.get_matter(account["matter_id"])["tenant_id"] == 1


def test_wrong_code_is_rejected(client, mailbox):
    _invite(client, "rahul@example.com")
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    real_code = mailbox.latest_code_for("rahul@example.com")
    wrong_code = "000000" if real_code != "000000" else "111111"

    response = client.post(
        "/end-user/auth/signup/complete",
        json={"email": "rahul@example.com", "code": wrong_code, "password": "correct-horse-1"},
    )
    assert response.status_code == 400


def test_code_stops_working_after_too_many_wrong_guesses(client, mailbox):
    _invite(client, "rahul@example.com")
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    real_code = mailbox.latest_code_for("rahul@example.com")
    wrong_code = "000000" if real_code != "000000" else "111111"

    for _ in range(5):
        client.post(
            "/end-user/auth/signup/complete",
            json={"email": "rahul@example.com", "code": wrong_code, "password": "correct-horse-1"},
        )

    response = client.post(
        "/end-user/auth/signup/complete",
        json={"email": "rahul@example.com", "code": real_code, "password": "correct-horse-1"},
    )
    assert response.status_code == 400


def test_expired_code_is_rejected(client, mailbox, repo):
    _invite(client, "rahul@example.com")
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    code = mailbox.latest_code_for("rahul@example.com")

    record = repo.get_latest_verification_code("rahul@example.com", "signup")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with repo._connect() as conn:
        conn.execute("UPDATE verification_codes SET expires_at = ? WHERE id = ?", (past, record["id"]))

    response = client.post(
        "/end-user/auth/signup/complete",
        json={"email": "rahul@example.com", "code": code, "password": "correct-horse-1"},
    )
    assert response.status_code == 400


def test_code_is_single_use(client, mailbox):
    _invite(client, "rahul@example.com")
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    code = mailbox.latest_code_for("rahul@example.com")
    payload = {"email": "rahul@example.com", "code": code, "password": "correct-horse-1"}

    assert client.post("/end-user/auth/signup/complete", json=payload).status_code == 200
    assert client.post("/end-user/auth/signup/complete", json=payload).status_code == 400


def test_codes_are_never_stored_in_plain_text(client, mailbox, repo):
    _invite(client, "rahul@example.com")
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    code = mailbox.latest_code_for("rahul@example.com")

    record = repo.get_latest_verification_code("rahul@example.com", "signup")
    assert code not in record["code_hash"]


def test_short_password_is_rejected(client, mailbox):
    _invite(client, "rahul@example.com")
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    code = mailbox.latest_code_for("rahul@example.com")

    response = client.post(
        "/end-user/auth/signup/complete", json={"email": "rahul@example.com", "code": code, "password": "short"}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------
# Login and what a session can reach
# ---------------------------------------------------------------------


def test_login_with_email_and_password(client, mailbox):
    _invite(client, "rahul@example.com")
    _sign_up(client, mailbox, "rahul@example.com", password="correct-horse-1")

    response = client.post("/end-user/auth/login", json={"email": "Rahul@Example.com", "password": "correct-horse-1"})
    assert response.status_code == 200
    assert response.json()["email"] == "rahul@example.com"


def test_wrong_password_and_unknown_email_get_the_same_error(client, mailbox):
    _invite(client, "rahul@example.com")
    _sign_up(client, mailbox, "rahul@example.com", password="correct-horse-1")

    wrong_password = client.post("/end-user/auth/login", json={"email": "rahul@example.com", "password": "nope-nope-1"})
    unknown_email = client.post("/end-user/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-1"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_end_user_session_reaches_intake_but_never_admin_endpoints(client, mailbox):
    _invite(client, "rahul@example.com")
    token = _sign_up(client, mailbox, "rahul@example.com")

    assert client.get("/end-user/intake/sessions", headers=_bearer(token)).status_code == 200
    assert client.get("/categories", headers=_bearer(token)).status_code == 403
    assert client.get("/admin/users", headers=_bearer(token)).status_code == 403
    assert client.get("/admin/matters", headers=_bearer(token)).status_code == 403


def test_owner_token_is_not_accepted_as_an_end_user_session(client):
    response = client.get("/end-user/intake/sessions", headers=_admin())
    assert response.status_code == 401


def test_each_user_only_sees_their_own_intake_sessions(client, mailbox):
    _invite(client, "rahul@example.com", "priya@example.com")
    rahul = _sign_up(client, mailbox, "rahul@example.com")
    priya = _sign_up(client, mailbox, "priya@example.com")

    client.post("/end-user/intake/sessions", json={"title": "Rahul's intake"}, headers=_bearer(rahul))

    rahul_sessions = client.get("/end-user/intake/sessions", headers=_bearer(rahul)).json()["sessions"]
    priya_sessions = client.get("/end-user/intake/sessions", headers=_bearer(priya)).json()["sessions"]

    assert [s["title"] for s in rahul_sessions] == ["Rahul's intake"]
    assert priya_sessions == []


# ---------------------------------------------------------------------
# Deactivation and password reset
# ---------------------------------------------------------------------


def test_deactivation_cuts_off_an_existing_session_immediately_and_blocks_login(client, mailbox):
    _invite(client, "rahul@example.com")
    token = _sign_up(client, mailbox, "rahul@example.com", password="correct-horse-1")
    user_id = client.get("/admin/users", headers=_admin()).json()["users"][0]["id"]

    deactivated = client.post(f"/admin/users/{user_id}/deactivate", headers=_admin())
    assert deactivated.json()["status"] == "deactivated"

    assert client.get("/end-user/intake/sessions", headers=_bearer(token)).status_code == 401
    login = client.post("/end-user/auth/login", json={"email": "rahul@example.com", "password": "correct-horse-1"})
    assert login.status_code == 403

    client.post(f"/admin/users/{user_id}/reactivate", headers=_admin())
    login_again = client.post("/end-user/auth/login", json={"email": "rahul@example.com", "password": "correct-horse-1"})
    assert login_again.status_code == 200


def test_deactivated_invite_cannot_complete_signup(client, mailbox):
    _invite(client, "rahul@example.com")
    user_id = client.get("/admin/users", headers=_admin()).json()["users"][0]["id"]
    client.post("/end-user/auth/signup/request-code", json={"email": "rahul@example.com"})
    code = mailbox.latest_code_for("rahul@example.com")

    client.post(f"/admin/users/{user_id}/deactivate", headers=_admin())

    response = client.post(
        "/end-user/auth/signup/complete",
        json={"email": "rahul@example.com", "code": code, "password": "correct-horse-1"},
    )
    assert response.status_code == 400


def test_password_reset_changes_the_password_and_ends_old_sessions(client, mailbox):
    _invite(client, "rahul@example.com")
    old_token = _sign_up(client, mailbox, "rahul@example.com", password="old-password-1")

    client.post("/end-user/auth/password-reset/request-code", json={"email": "rahul@example.com"})
    code = mailbox.latest_code_for("rahul@example.com")
    reset = client.post(
        "/end-user/auth/password-reset/complete",
        json={"email": "rahul@example.com", "code": code, "new_password": "new-password-1"},
    )
    assert reset.status_code == 200

    assert client.get("/end-user/auth/me", headers=_bearer(old_token)).status_code == 401
    assert client.post(
        "/end-user/auth/login", json={"email": "rahul@example.com", "password": "old-password-1"}
    ).status_code == 401
    assert client.post(
        "/end-user/auth/login", json={"email": "rahul@example.com", "password": "new-password-1"}
    ).status_code == 200


def test_password_reset_code_is_not_sent_to_unregistered_email(client, mailbox):
    response = client.post("/end-user/auth/password-reset/request-code", json={"email": "ghost@example.com"})

    assert response.status_code == 200
    assert mailbox.sent == []


def test_console_email_provider_is_refused_in_production(monkeypatch):
    from types import SimpleNamespace

    from app.notifications import email_sender

    monkeypatch.setattr(
        email_sender, "get_settings", lambda: SimpleNamespace(email_provider="console", environment="production")
    )

    with pytest.raises(RuntimeError, match="not allowed"):
        email_sender.get_email_sender()


def test_failed_code_email_never_logs_the_code(repo, monkeypatch, caplog):
    """A send failure (e.g. a wrong Gmail App Password) is logged - but the live code must not appear in the log."""

    from app.security import end_user_accounts

    class _FailingSender:
        def __init__(self):
            self.subjects: list[str] = []

        def send(self, to_email: str, subject: str, body: str) -> None:
            self.subjects.append(subject)
            raise RuntimeError("535 Username and Password not accepted")

    sender = _FailingSender()
    monkeypatch.setattr("app.notifications.email_sender.get_email_sender", lambda: sender)
    end_user_accounts.invite_end_users(repo, ["someone@example.com"], tenant_id=1, invited_by="admin@example.com")

    with caplog.at_level("ERROR"):
        end_user_accounts.request_code(repo, "someone@example.com", end_user_accounts.PURPOSE_SIGNUP)

    code = re.search(r"\b(\d{6})\b", sender.subjects[-1]).group(1)
    assert "Could not send signup code email to someone@example.com" in caplog.text
    assert code not in caplog.text

"""
Upload virus scanning (app/security/virus_scan.py): the clamd INSTREAM
protocol against a fake clamd server, and every upload path - library
upload and replace, vault sync, client intake, compare - refusing an
infected file, and refusing any file when scanning is on but no verdict
can be had (fails closed).
"""

import io
import socket
import socketserver
import struct
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security import virus_scan
from app.storage.local_backend import LocalStorageBackend
from config.settings import get_settings

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class _FakeClamd(socketserver.BaseRequestHandler):
    """Speaks the clamd INSTREAM/PING protocol; flags anything containing the EICAR string."""

    received: list[bytes] = []

    def handle(self):
        command = b""
        while not command.endswith(b"\0"):
            command += self.request.recv(1)
        if command == b"zPING\0":
            self.request.sendall(b"PONG\0")
            return
        data = b""
        while True:
            (length,) = struct.unpack("!L", self._read(4))
            if length == 0:
                break
            data += self._read(length)
        _FakeClamd.received.append(data)
        if b"SIZE-LIMIT" in data:
            self.request.sendall(b"INSTREAM size limit exceeded. ERROR\0")
        elif EICAR in data:
            self.request.sendall(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
        else:
            self.request.sendall(b"stream: OK\0")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            buf += self.request.recv(n - len(buf))
        return buf


@pytest.fixture
def clamd(monkeypatch):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _FakeClamd)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = get_settings()
    monkeypatch.setattr(settings, "virus_scanner", "clamav")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.server_address[1])
    monkeypatch.setattr(settings, "clamav_socket", "")
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 5)
    _FakeClamd.received = []
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def clamd_down(monkeypatch):
    with socket.socket() as probe:  # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = get_settings()
    monkeypatch.setattr(settings, "virus_scanner", "clamav")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)
    monkeypatch.setattr(settings, "clamav_socket", "")
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 2)


# ----------------------------------------------------------------------
# The scanner itself
# ----------------------------------------------------------------------

def test_scanning_off_by_default_marks_files_unscanned(monkeypatch):
    monkeypatch.setattr(get_settings(), "virus_scanner", "none")
    assert virus_scan.scan_bytes(EICAR) == virus_scan.ScanResult(clean=True, scanned=False)


def test_instream_clean_infected_and_multi_chunk(clamd):
    assert virus_scan.scan_bytes(b"hello").clean is True
    infected = virus_scan.scan_bytes(b"prefix " + EICAR)
    assert (infected.clean, infected.signature) == (False, "Win.Test.EICAR_HDB-1")

    big = bytes(range(256)) * 1000  # 256 KB -> several 64 KB chunks
    assert virus_scan.scan_bytes(big).clean is True
    assert _FakeClamd.received[-1] == big
    assert virus_scan.ping() is True


def test_no_verdict_fails_closed(clamd, clamd_down):
    with pytest.raises(virus_scan.ScannerUnavailable):
        virus_scan.scan_bytes(b"hello")
    assert virus_scan.ping() is False


def test_size_limit_and_unknown_scanner_fail_closed(clamd, monkeypatch):
    with pytest.raises(virus_scan.ScannerUnavailable, match="StreamMaxLength"):
        virus_scan.scan_bytes(b"SIZE-LIMIT")
    monkeypatch.setattr(get_settings(), "virus_scanner", "norton")
    with pytest.raises(virus_scan.ScannerUnavailable):
        virus_scan.scan_bytes(b"hello")


@pytest.mark.parametrize("reply, expected", [
    ("stream: OK", virus_scan.ScanResult(clean=True)),
    ("stream: Eicar-Signature FOUND", virus_scan.ScanResult(clean=False, signature="Eicar-Signature")),
])
def test_parse_clamd_reply(reply, expected):
    assert virus_scan.parse_clamd_reply(reply) == expected


def test_parse_clamd_error_raises():
    with pytest.raises(virus_scan.ScannerUnavailable):
        virus_scan.parse_clamd_reply("stream: Can't allocate memory ERROR")


# ----------------------------------------------------------------------
# Every upload path
# ----------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = SQLiteMetadataRepository(tmp_path / "metadata.db")
    storage = LocalStorageBackend(originals_dir=tmp_path / "originals", quarantine_dir=tmp_path / "quarantine")
    monkeypatch.setattr(storage_api, "metadata_repository", repo)
    monkeypatch.setattr(storage_api, "storage_backend", storage)
    return SimpleNamespace(repo=repo, storage=storage, tmp=tmp_path, client=TestClient(storage_api.app))


def _upload(env, name, content):
    return env.client.post("/categories/Wage/documents", files={"file": (name, io.BytesIO(content), "text/plain")})


def test_library_upload_infected_goes_to_quarantine_not_the_library(env, clamd):
    clean = _upload(env, "policy.txt", b"Overtime after 8 hours.").json()
    infected = _upload(env, "bad.txt", b"note " + EICAR).json()

    assert clean["results"][0]["status"] == "stored"
    assert infected["results"][0]["status"] == "rejected"
    assert "virus detected (Win.Test.EICAR_HDB-1)" in infected["results"][0]["reason"]
    assert [d["filename"] for d in env.repo.list_documents(tenant_id=1)] == ["policy.txt"]
    assert list((env.tmp / "quarantine").rglob("bad.txt"))
    assert not list((env.tmp / "originals").rglob("bad.txt"))


def test_library_upload_refused_when_scanner_is_down(env, clamd_down):
    result = _upload(env, "policy.txt", b"Overtime after 8 hours.").json()["results"][0]

    assert result["status"] == "rejected"
    assert "not stored" in result["reason"]
    assert env.repo.list_documents(tenant_id=1) == []


def test_replace_with_an_infected_file_keeps_the_current_one(env, clamd):
    _upload(env, "policy.txt", b"Overtime after 8 hours.")

    response = env.client.put(
        "/categories/Wage/documents/policy.txt", files={"file": ("policy.txt", io.BytesIO(EICAR), "text/plain")}
    )

    assert response.status_code == 400
    assert "Virus detected" in response.json()["detail"]
    assert (env.tmp / "originals" / "tenant-1" / "Wage" / "policy.txt").read_bytes() == b"Overtime after 8 hours."


def test_vault_sync_skips_infected_files_and_retries_them(env, clamd, _fake_vector_store):
    from app.vault_sync.folder_sync import sync_folder

    source = env.tmp / "Dropbox"
    (source / "Wage").mkdir(parents=True)
    (source / "Wage" / "ok.txt").write_text("Overtime after 8 hours.")
    (source / "Wage" / "bad.txt").write_bytes(EICAR)

    result = sync_folder(source, 1, env.repo, env.storage, _fake_vector_store)

    assert result.added == 1
    assert [s["path"] for s in result.skipped] == ["Wage/bad.txt"]
    assert "virus detected" in result.skipped[0]["reason"]
    assert [row["source_path"] for row in env.repo.list_vault_manifest(1)] == ["Wage/ok.txt"]
    # not in the manifest -> checked again next run
    assert [s["path"] for s in sync_folder(source, 1, env.repo, env.storage, _fake_vector_store).skipped] == ["Wage/bad.txt"]


@pytest.fixture
def intake_client(env, monkeypatch):
    import app.api.intake_api as intake_api
    import app.storage as storage_module
    from tests.conftest import _FakeQueue

    intake_backend = LocalStorageBackend(originals_dir=env.tmp / "intake", quarantine_dir=env.tmp / "intake_quarantine")
    monkeypatch.setattr(storage_module, "get_intake_storage_backend", lambda: intake_backend)
    monkeypatch.setattr(intake_api, "get_job_queue", lambda: _FakeQueue())
    return env.client


def test_intake_upload_infected_is_refused_with_a_plain_message(env, intake_client, clamd):
    session_id = intake_client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    response = intake_client.post(
        f"/end-user/intake/sessions/{session_id}/uploads", files={"file": ("stub.txt", io.BytesIO(EICAR), "text/plain")}
    )

    assert response.status_code == 400
    assert "virus" in response.json()["detail"]
    assert env.repo.list_uploaded_inputs(session_id) == []
    assert list((env.tmp / "intake_quarantine").rglob("stub.txt"))
    events = [e["event_type"] for e in env.repo.list_timeline_events(session_id)]
    assert "upload_blocked" in events


def test_intake_upload_waits_for_the_scanner(env, intake_client, clamd_down):
    session_id = intake_client.post("/end-user/intake/sessions", json={"title": "Intake"}).json()["id"]

    response = intake_client.post(
        f"/end-user/intake/sessions/{session_id}/uploads", files={"file": ("stub.txt", io.BytesIO(b"hi"), "text/plain")}
    )

    assert response.status_code == 503
    assert env.repo.list_uploaded_inputs(session_id) == []


def test_compare_upload_infected_is_refused(env, clamd):
    response = env.client.post("/end-user/compare", files={"file": ("x.txt", io.BytesIO(EICAR), "text/plain")})

    assert response.status_code == 400
    assert "virus" in response.json()["detail"]

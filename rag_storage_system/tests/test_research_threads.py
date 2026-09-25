"""
Owner research threads + streaming (app/api/research_threads_api.py):
answers stream as SSE, every completed Q&A is saved to its thread with its
locked sources, threads belong to one admin user in one organization, and
a whole thread exports as a research memorandum. Real auth tokens.
"""

import io
import json
from types import SimpleNamespace

import docx
import pytest
from fastapi.testclient import TestClient

from app.api import storage_api
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.security.auth import create_access_token, require_admin_key


@pytest.fixture
def client(tmp_path, monkeypatch):
    storage_api.app.dependency_overrides.pop(require_admin_key, None)
    monkeypatch.setattr(storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db"))
    monkeypatch.setattr(storage_api, "retrieve", lambda query, **kwargs: [_hit()])
    yield TestClient(storage_api.app)
    storage_api.app.dependency_overrides.pop(require_admin_key, None)


def _hit():
    return {
        "chunk_id": "c-1", "document_id": "d", "category": "Harassment", "filename": "10.6_Discovery_Issues.pdf",
        "chunk_text": "A formal noticed motion for discovery is required. [CCP § 2017.220(a)]",
        "section": None, "start_page": 2, "end_page": 2, "final_score": 0.51,
    }


def _as(owner_id: int, tenant_id: int = 1) -> dict:
    token = create_access_token(owner_id=owner_id, email=f"a{owner_id}@firm.com", tenant_id=tenant_id, role="attorney")
    return {"Authorization": f"Bearer {token}"}


def _ask(client, headers, query, thread_id=None) -> list[tuple[str, dict]]:
    body = {"query": query} | ({"thread_id": thread_id} if thread_id else {})
    response = client.post("/research/ask/stream", json=body, headers=headers)
    assert response.status_code == 200, response.text
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_a_streamed_answer_starts_a_thread_and_is_saved_with_its_sources(client):
    events = _ask(client, _as(1), "What must an employer show to get discovery of sexual conduct?")

    assert [e for e, _ in events][:2] == ["thread", "sources"]
    assert events[-1][0] == "done"
    thread_id = events[0][1]["thread_id"]
    assert events[0][1]["title"] == "What must an employer show to get discovery of sexual conduct?"

    _ask(client, _as(1), "Is a mental examination allowed?", thread_id=thread_id)

    detail = client.get(f"/research/threads/{thread_id}", headers=_as(1)).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["sources"][0]["excerpt"].startswith("A formal noticed motion")
    assert client.get("/research/threads", headers=_as(1)).json()["threads"][0]["message_count"] == 4


def test_threads_belong_to_one_user_in_one_organization(client):
    thread_id = _ask(client, _as(1), "Question one")[0][1]["thread_id"]

    for outsider in (_as(2), _as(1, tenant_id=2)):  # a colleague in the same firm, and another firm
        assert client.get(f"/research/threads/{thread_id}", headers=outsider).status_code == 404
        assert client.post(f"/research/threads/{thread_id}/export", json={"format": "docx"}, headers=outsider).status_code == 404
        assert client.delete(f"/research/threads/{thread_id}", headers=outsider).status_code == 404
        adding = client.post("/research/ask/stream", json={"query": "sneak in", "thread_id": thread_id}, headers=outsider)
        assert adding.status_code == 404
        assert client.get("/research/threads", headers=outsider).json()["threads"] == []


def test_rename_and_delete(client):
    thread_id = _ask(client, _as(1), "Question one")[0][1]["thread_id"]

    assert client.patch(f"/research/threads/{thread_id}", json={"title": "Discovery memo"}, headers=_as(1)).json()["title"] == "Discovery memo"
    assert client.delete(f"/research/threads/{thread_id}", headers=_as(1)).status_code == 200
    assert client.get(f"/research/threads/{thread_id}", headers=_as(1)).status_code == 404


def test_an_answer_that_failed_is_not_saved(client, monkeypatch):
    monkeypatch.setattr(
        "app.analysis.relevance_guard.get_settings",
        lambda: SimpleNamespace(anthropic_api_key="test-key", analysis_model="claude-opus-5"),
    )

    class _Broken:
        def create(self, **kwargs):
            raise RuntimeError("credit balance too low")

    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: SimpleNamespace(messages=_Broken()))

    events = _ask(client, _as(1), "Question one")

    assert any(e == "error" for e, _ in events)
    thread_id = events[0][1]["thread_id"]
    assert client.get(f"/research/threads/{thread_id}", headers=_as(1)).json()["messages"] == []


def test_a_thread_exports_as_one_memorandum(client):
    thread_id = _ask(client, _as(1), "What must an employer show?")[0][1]["thread_id"]
    _ask(client, _as(1), "What about the spouse?", thread_id=thread_id)

    response = client.post(f"/research/threads/{thread_id}/export", json={"format": "docx"}, headers=_as(1))

    assert response.status_code == 200
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(response.content)).paragraphs)
    assert "Research Memorandum" in text
    assert "Question Presented 1" in text and "Question Presented 2" in text
    assert "What about the spouse?" in text
    assert "Authorities Cited" in text
    assert "“A formal noticed motion for discovery is required." in text
    assert "FROM: a1@firm.com" in text

    pdf = client.post(f"/research/threads/{thread_id}/export", json={"format": "pdf"}, headers=_as(1))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_an_empty_thread_has_nothing_to_export(client):
    thread = client.post("/research/threads", json={}, headers=_as(1)).json()
    assert thread["title"] == "New research"
    response = client.post(f"/research/threads/{thread['id']}/export", json={"format": "pdf"}, headers=_as(1))
    assert response.status_code == 400

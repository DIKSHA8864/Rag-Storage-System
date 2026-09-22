"""
End-to-end tests for app/api/end_user_api.py (POST /end-user/query,
POST /end-user/compare). Auth itself is covered in tests/test_auth.py
- conftest.py's autouse fixture bypasses both auth scopes here, same
as every other non-auth test file.

Real ingestion (extraction/segmentation/chunking/embedding - loads the
real embedding model, same as other tests) runs for real; only
app/analysis/matcher.py's call into app/retrieval/retriever.retrieve()
is mocked, so these tests control what the "knowledge base" appears to
contain without needing real Postgres/pgvector.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.analysis import matcher
from app.api import end_user_api, storage_api


@pytest.fixture
def client():
    return TestClient(storage_api.app)


def _hit(chunk_id="c-1", score=0.9, filename="policy.pdf", section="1.1"):
    return {
        "chunk_id": chunk_id,
        "document_id": "policy",
        "category": "Docs",
        "filename": filename,
        "chunk_text": "The policy requires annual review of all vendor contracts.",
        "chapter": None,
        "section": section,
        "start_page": 1,
        "end_page": 1,
        "metadata": {},
        "vector_score": score,
        "keyword_score": 0.0,
        "final_score": score,
    }


# ---------------------------------------------------------------------
# POST /end-user/query
# ---------------------------------------------------------------------


def test_query_returns_results_from_retrieve(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda query, top_k, category=None: [_hit()])
    monkeypatch.setattr(end_user_api, "retrieve_for_matter", lambda query, matter_id, top_k=5, score_threshold=0.0: [_hit()])

    response = client.post("/end-user/query", json={"query": "vendor contract review"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "vendor contract review"
    assert len(body["results"]) == 1
    assert body["results"][0]["filename"] == "policy.pdf"
    assert body["results"][0]["section"] == "1.1"


def test_query_rejects_empty_query(client):
    response = client.post("/end-user/query", json={"query": ""})
    assert response.status_code == 422


# ---------------------------------------------------------------------
# POST /end-user/compare
# ---------------------------------------------------------------------


def test_compare_requires_exactly_one_of_query_or_file(client):
    assert client.post("/end-user/compare", data={}).status_code == 400

    response = client.post(
        "/end-user/compare",
        data={"query": "some text"},
        files={"file": ("report.txt", io.BytesIO(b"content"), "text/plain")},
    )
    assert response.status_code == 400


def test_compare_with_pasted_text_returns_full_report(client, monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [_hit()])

    response = client.post(
        "/end-user/compare",
        data={"query": "All vendor contracts must be reviewed annually."},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["insufficient_evidence"] is False
    assert report["overall_match_score"] > 0
    assert "match_score_breakdown" in report
    assert report["detailed_matching"]["similarities"]
    assert report["sources"]
    assert report["provenance_legend"]["retrieved"]


def test_compare_with_no_evidence_returns_insufficient_information(client, monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [])

    response = client.post(
        "/end-user/compare",
        data={"query": "Something totally unrelated to anything."},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["insufficient_evidence"] is True
    assert report["executive_summary"]["text"] == (
        "Insufficient information found in the available knowledge base."
    )
    assert report["overall_match_score"] == 0.0


def test_compare_with_file_upload(client, monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [_hit()])

    response = client.post(
        "/end-user/compare",
        files={
            "file": (
                "submission.txt",
                io.BytesIO(b"All vendor contracts must be reviewed annually."),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["insufficient_evidence"] is False


def test_compare_rejects_unsupported_file_type(client):
    response = client.post(
        "/end-user/compare",
        files={"file": ("recording.mp3", io.BytesIO(b"not audio"), "audio/mpeg")},
    )

    assert response.status_code == 400
    assert "Audio/video" in response.json()["detail"]

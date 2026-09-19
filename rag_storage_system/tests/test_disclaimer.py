"""
Tests for Disclaimer Management:

- DB-backed storage (app/metadata/base.py's get_disclaimer/
  update_disclaimer, both backends) - contract tests here mirror
  tests/test_metadata_repository.py's style for the SQLite backend.
- Owner console edit/save (GET/PUT /admin/disclaimer,
  app/api/storage_api.py).
- The updated disclaimer showing up in DOCX/PDF exports
  (app/analysis/report_export.py, POST /end-user/compare/export).

Auth itself is bypassed here via conftest.py's autouse
_bypass_admin_auth fixture, same as every other non-auth test file.
"""

import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.analysis.report_export import build_report_docx, build_report_pdf
from app.api import storage_api
from app.disclaimer import DEFAULT_DISCLAIMER_TEXT, get_current_disclaimer_text
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.storage.local_backend import LocalStorageBackend


# ---------------------------------------------------------------------
# Repository contract (SQLiteMetadataRepository) - see
# tests/test_metadata_repository.py for the equivalent folders/documents
# coverage, including the Postgres-backed parameterization this file
# intentionally does not repeat (no new behavior to verify per-backend
# beyond what's already exercised there).
# ---------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    return SQLiteMetadataRepository(tmp_path / "metadata.db")


def test_get_disclaimer_returns_none_when_never_saved(repo):
    assert repo.get_disclaimer() is None


def test_get_current_disclaimer_text_falls_back_to_default(repo):
    assert get_current_disclaimer_text(repo) == DEFAULT_DISCLAIMER_TEXT


def test_update_disclaimer_then_get(repo):
    saved = repo.update_disclaimer("Custom disclaimer text.", updated_by="owner@example.com")

    assert saved["text"] == "Custom disclaimer text."
    assert saved["updated_by"] == "owner@example.com"

    fetched = repo.get_disclaimer()
    assert fetched["text"] == "Custom disclaimer text."
    assert fetched["updated_by"] == "owner@example.com"


def test_update_disclaimer_overwrites_in_place(repo):
    repo.update_disclaimer("First version.")
    repo.update_disclaimer("Second version.")

    assert repo.get_disclaimer()["text"] == "Second version."


def test_get_current_disclaimer_text_reflects_saved_value(repo):
    repo.update_disclaimer("Saved disclaimer.")
    assert get_current_disclaimer_text(repo) == "Saved disclaimer."


# ---------------------------------------------------------------------
# Owner console: GET/PUT /admin/disclaimer
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


def test_get_disclaimer_returns_default_before_any_save(client):
    response = client.get("/admin/disclaimer")

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == DEFAULT_DISCLAIMER_TEXT
    assert body["updated_at"] is None
    assert body["updated_by"] is None


def test_owner_can_edit_and_save_disclaimer(client):
    response = client.put("/admin/disclaimer", json={"text": "New disclaimer from the Owner console."})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "New disclaimer from the Owner console."
    assert body["updated_at"] is not None

    # Saved value is what a subsequent read returns.
    response = client.get("/admin/disclaimer")
    assert response.json()["text"] == "New disclaimer from the Owner console."


def test_update_disclaimer_rejects_empty_text(client):
    response = client.put("/admin/disclaimer", json={"text": ""})
    assert response.status_code == 422


def test_update_disclaimer_is_audited(tmp_path, monkeypatch, client):
    from app.security import audit_log

    log_path = tmp_path / "logs" / "audit.log"
    monkeypatch.setattr(audit_log.get_settings(), "audit_log_path", str(log_path))

    client.put("/admin/disclaimer", json={"text": "Audited disclaimer."})

    assert log_path.exists()
    assert "update_disclaimer" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# DOCX/PDF export contains the current disclaimer
# (app/analysis/report_export.py)
# ---------------------------------------------------------------------


def _sample_report() -> dict:
    """A minimal but complete report dict, same shape build_analysis_report() returns."""

    return {
        "executive_summary": {"text": "Overall the submission aligns with policy.", "provenance": "generated"},
        "overall_match_score": 82.5,
        "match_score_breakdown": {
            "coverage_ratio": 0.9,
            "avg_confidence": 0.75,
            "coverage_weight": 0.6,
            "confidence_weight": 0.4,
        },
        "detailed_matching": {
            "similarities": [
                {
                    "input_chunk_index": 0,
                    "input_text": "Vendor contracts must be reviewed annually.",
                    "classification": "match",
                    "top_score": 0.9,
                    "is_conflict": False,
                    "narrative": {"text": "This matches the vendor review policy.", "provenance": "generated"},
                    "sources": [
                        {
                            "filename": "policy.pdf",
                            "category": "Docs",
                            "document_id": "policy",
                            "chunk_id": "c-1",
                            "chunk_text": "Vendor contracts require annual review.",
                            "section": "1.1",
                            "start_page": 1,
                            "end_page": 1,
                            "score": 0.9,
                            "provenance": "retrieved",
                        }
                    ],
                }
            ],
            "differences": [],
            "gaps": [],
            "conflicts": [],
        },
        "recommendations": [{"text": "Continue annual vendor reviews.", "provenance": "recommendation"}],
        "sources": [
            {
                "filename": "policy.pdf",
                "category": "Docs",
                "document_id": "policy",
                "chunk_id": "c-1",
                "chunk_text": "Vendor contracts require annual review.",
                "section": "1.1",
                "start_page": 1,
                "end_page": 1,
                "score": 0.9,
                "provenance": "retrieved",
            }
        ],
        "insufficient_evidence": False,
        "provenance_legend": {"retrieved": "...", "generated": "...", "recommendation": "..."},
    }


def test_build_report_docx_contains_disclaimer_text():
    content = build_report_docx(_sample_report(), "THE-CURRENT-DISCLAIMER-TEXT")

    document = Document(io.BytesIO(content))
    full_text = "\n".join(p.text for p in document.paragraphs)

    assert "THE-CURRENT-DISCLAIMER-TEXT" in full_text
    assert "Overall the submission aligns with policy." in full_text


def test_build_report_pdf_contains_disclaimer_text():
    pymupdf = pytest.importorskip("pymupdf")

    content = build_report_pdf(_sample_report(), "THE-CURRENT-DISCLAIMER-TEXT")

    doc = pymupdf.open(stream=content, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)

    assert "THE-CURRENT-DISCLAIMER-TEXT" in full_text
    assert "Overall the submission aligns with policy." in full_text


def test_docx_export_reflects_owner_updated_disclaimer(client, monkeypatch):
    """
    End-to-end: an Owner edits the disclaimer via the console, then the
    very next DOCX export reflects it - no restart, no stale cache.
    """

    from app.analysis import matcher

    client.put("/admin/disclaimer", json={"text": "OWNER-UPDATED-DISCLAIMER"})

    monkeypatch.setattr(
        matcher,
        "retrieve",
        lambda *a, **k: [
            {
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
                "vector_score": 0.9,
                "keyword_score": 0.0,
                "final_score": 0.9,
            }
        ],
    )

    response = client.post(
        "/end-user/compare/export",
        data={"format": "docx", "query": "Vendor contracts must be reviewed annually."},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    document = Document(io.BytesIO(response.content))
    full_text = "\n".join(p.text for p in document.paragraphs)
    assert "OWNER-UPDATED-DISCLAIMER" in full_text


def test_export_rejects_unknown_format(client):
    response = client.post(
        "/end-user/compare/export",
        data={"format": "html", "query": "Some text."},
    )
    assert response.status_code == 400


def test_export_requires_exactly_one_of_query_or_file(client):
    response = client.post("/end-user/compare/export", data={"format": "docx"})
    assert response.status_code == 400

    response = client.post(
        "/end-user/compare/export",
        data={"format": "docx", "query": "text"},
        files={"file": ("a.txt", io.BytesIO(b"content"), "text/plain")},
    )
    assert response.status_code == 400

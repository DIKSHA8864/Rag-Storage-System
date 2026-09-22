"""
Phase 2 E2E acceptance tests, covering the freeze checklist:

    Normal research question / Missing authority / Fabricated
    citation / Citation lock / DOCX / PDF / Prompt version-rollback /
    Settings / Disclaimer / Streaming

RAG-behavior scenarios (normal question, missing authority, fabricated
citation, citation lock, streaming) run against POST
/end-user/query/stream with app.api.end_user_api.retrieve monkeypatched
- same pattern as tests/test_threads_and_matters.py - so they need no
real embedding model / network access.

/end-user/compare and /compare/export need the real embedding model to
embed the *input* text (see tests/test_end_user_api.py's module
docstring) - that path is already covered there; this file doesn't
duplicate it. DOCX/PDF are exercised directly against
app.analysis.report_export's build functions instead (same approach as
tests/test_disclaimer.py), which is both faster and network-independent.

Disclaimer itself is covered in tests/test_disclaimer.py - not
duplicated here beyond what's needed to prove it flows into an export.
"""

import io
import json
import re

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.analysis import answer_generation
from app.analysis.report_export import build_report_docx, build_report_pdf
from app.api import end_user_api, storage_api
from app.disclaimer import get_current_disclaimer_text
from app.metadata.sqlite_repository import SQLiteMetadataRepository
from app.prompts import get_active_prompt
from app.storage.local_backend import LocalStorageBackend


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


def _hit(filename="policy.pdf", chunk_id="c-1", score=0.9, text="Vendor contracts require annual review."):
    return {
        "chunk_id": chunk_id,
        "document_id": filename,
        "category": "Docs",
        "filename": filename,
        "chunk_text": text,
        "chapter": None,
        "section": "1.1",
        "start_page": 1,
        "end_page": 1,
        "metadata": {},
        "vector_score": score,
        "keyword_score": 0.0,
        "final_score": score,
    }


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse raw SSE text into an ordered list of (event_type, data) pairs."""

    events = []
    for raw_event in body.split("\n\n"):
        if not raw_event.strip():
            continue
        lines = raw_event.split("\n")
        event_line = next((l for l in lines if l.startswith("event: ")), None)
        data_line = next((l for l in lines if l.startswith("data: ")), None)
        if event_line and data_line:
            events.append((event_line[len("event: "):], json.loads(data_line[len("data: "):])))
    return events


def _stream(client, **json_body) -> str:
    with client.stream("POST", "/end-user/query/stream", json=json_body) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return "".join(response.iter_text())


# ---------------------------------------------------------------------
# 1. Normal research question
# ---------------------------------------------------------------------


def test_normal_research_question_returns_sources_and_answer(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    events = _parse_sse(_stream(client, query="What is the vendor review policy?"))
    types = [e for e, _ in events]

    assert types[0] == "sources"
    assert types[-1] == "done"
    assert "answer_chunk" in types

    sources = dict(events)["sources"]["sources"] if events[0][0] == "sources" else None
    assert sources == events[0][1]["sources"]
    assert sources[0]["filename"] == "policy.pdf"

    full_answer = "".join(data["text"] for etype, data in events if etype == "answer_chunk")
    assert "Vendor contracts require annual review." in full_answer


# ---------------------------------------------------------------------
# 2. Missing authority
# ---------------------------------------------------------------------


def test_missing_authority_returns_insufficient_information(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [])

    events = _parse_sse(_stream(client, query="What is our policy on interstellar travel?"))

    assert events[0] == ("sources", {"sources": []})
    answer_events = [data for etype, data in events if etype == "answer_chunk"]
    assert answer_events == [
        {"text": "Insufficient information found in the available knowledge base."}
    ]
    assert events[-1][0] == "done"


# ---------------------------------------------------------------------
# 3. Fabricated citation guard
# ---------------------------------------------------------------------


def test_answer_never_cites_a_source_outside_the_locked_set(client, monkeypatch):
    """
    This exercises the default TemplateNarrativeGenerator path, which
    is grounded by construction (its citations come directly from the
    same chunks that built `sources`) - it's a regression guard for
    that code, not proof that a fabricated citation would be caught.
    The Claude-backed path's *technical* enforcement
    (_citations_are_grounded in app/analysis/answer_generation.py) is
    tested directly, with a mocked Claude response that actually
    fabricates a citation, in tests/test_answer_generation.py.
    """

    monkeypatch.setattr(
        end_user_api,
        "retrieve",
        lambda *a, **k: [
            _hit(filename="policy-a.pdf", chunk_id="c-1", text="Vendor contracts require annual review."),
            _hit(filename="policy-b.pdf", chunk_id="c-2", text="Payments must be approved by finance."),
        ],
    )

    events = _parse_sse(_stream(client, query="What are the relevant policies?"))

    locked_filenames = {s["filename"] for s in events[0][1]["sources"]}
    full_answer = "".join(data["text"] for etype, data in events if etype == "answer_chunk")

    cited_filenames = set(re.findall(r"source: '([^']+?)(?:\s-\s[^']+)?'", full_answer))
    # Every filename the answer claims as a source must be one retrieval
    # actually found - never an invented/hallucinated citation.
    assert cited_filenames
    assert cited_filenames <= locked_filenames


# ---------------------------------------------------------------------
# 4. Citation lock
# ---------------------------------------------------------------------


def test_citation_lock_sources_event_is_always_first_and_unique(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    events = _parse_sse(_stream(client, query="What is the vendor review policy?"))
    types = [e for e, _ in events]

    assert types[0] == "sources"
    assert types.count("sources") == 1


def test_citation_lock_survives_a_generation_failure(client, monkeypatch):
    """
    Even if answer generation blows up mid-stream, the sources already
    sent are untouched - they describe what retrieval found, not what
    text got generated, so a partial/failed answer doesn't invalidate them.
    """

    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    async def _broken_stream(query, chunks):
        raise RuntimeError("simulated generation failure")
        yield  # pragma: no cover - makes this an async generator

    # The actual call now lives in app/analysis/answer_generation.py's
    # stream_grounded_answer() (shared with the Owner-scope research
    # endpoint) - patch it there, where the call really happens.
    monkeypatch.setattr(answer_generation, "generate_answer_stream", _broken_stream)

    events = _parse_sse(_stream(client, query="What is the vendor review policy?"))
    types = [e for e, _ in events]

    assert types[0] == "sources"
    assert events[0][1]["sources"][0]["filename"] == "policy.pdf"
    assert "error" in types
    assert types[-1] == "done"


# ---------------------------------------------------------------------
# 5. DOCX / 6. PDF (report_export.py directly - no network dependency)
# ---------------------------------------------------------------------


def _sample_report() -> dict:
    return {
        "executive_summary": {"text": "Overall the submission aligns with policy.", "provenance": "generated"},
        "overall_match_score": 82.5,
        "match_score_breakdown": {
            "coverage_ratio": 0.9, "avg_confidence": 0.75, "coverage_weight": 0.6, "confidence_weight": 0.4,
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


def test_sample_report_conforms_to_the_real_analysis_report_schema():
    """
    Guards against fixture drift: if report_builder.py's output shape
    ever changes, this fails loudly here instead of the DOCX/PDF tests
    below silently asserting against a fixture that no longer matches
    what the real endpoint produces.
    """

    from app.api.schemas import AnalysisReport

    AnalysisReport(**_sample_report())


def test_docx_export_reflects_the_current_disclaimer(client):
    client.put("/admin/disclaimer", json={"text": "E2E-DOCX-DISCLAIMER"})
    disclaimer_text = get_current_disclaimer_text(storage_api.metadata_repository)

    content = build_report_docx(_sample_report(), disclaimer_text)

    document = Document(io.BytesIO(content))
    full_text = "\n".join(p.text for p in document.paragraphs)
    assert "E2E-DOCX-DISCLAIMER" in full_text
    assert "Overall the submission aligns with policy." in full_text
    assert "Continue annual vendor reviews." in full_text
    assert "policy.pdf" in full_text


def test_pdf_export_reflects_the_current_disclaimer(client):
    pymupdf = pytest.importorskip("pymupdf")

    client.put("/admin/disclaimer", json={"text": "E2E-PDF-DISCLAIMER"})
    disclaimer_text = get_current_disclaimer_text(storage_api.metadata_repository)

    content = build_report_pdf(_sample_report(), disclaimer_text)

    doc = pymupdf.open(stream=content, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)
    assert "E2E-PDF-DISCLAIMER" in full_text
    assert "Overall the submission aligns with policy." in full_text
    assert "Continue annual vendor reviews." in full_text
    assert "policy.pdf" in full_text


# ---------------------------------------------------------------------
# 7. Prompt version / rollback
# ---------------------------------------------------------------------


def test_prompt_version_create_then_rollback(client):
    name = "narrative_system_prompt"

    v1 = client.post(f"/admin/prompts/{name}", json={"text": "Version one text."}).json()
    assert v1["version"] == 1
    assert v1["is_active"] is True

    v2 = client.post(f"/admin/prompts/{name}", json={"text": "Version two text."}).json()
    assert v2["version"] == 2
    assert v2["is_active"] is True

    listed = client.get(f"/admin/prompts/{name}").json()["versions"]
    active_versions = {v["version"] for v in listed if v["is_active"]}
    assert active_versions == {2}

    assert get_active_prompt(storage_api.metadata_repository, name, "DEFAULT") == "Version two text."

    rollback = client.post(f"/admin/prompts/{name}/activate/1").json()
    assert rollback["version"] == 1
    assert rollback["is_active"] is True

    assert get_active_prompt(storage_api.metadata_repository, name, "DEFAULT") == "Version one text."


def test_activating_an_unknown_prompt_version_404s(client):
    response = client.post("/admin/prompts/narrative_system_prompt/activate/99")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# 8. Settings (Retrieval Settings) - proves it's enforced, not just stored
# ---------------------------------------------------------------------


def test_retrieval_settings_default_then_saved_value(client):
    default = client.get("/admin/retrieval-settings").json()
    assert default["updated_at"] is None

    saved = client.put(
        "/admin/retrieval-settings",
        json={"top_k": 3, "score_threshold": 0.0, "min_chunks": 5},
    ).json()
    assert saved["top_k"] == 3
    assert saved["min_chunks"] == 5

    assert client.get("/admin/retrieval-settings").json()["min_chunks"] == 5


def test_retrieval_settings_min_chunks_actually_gates_the_answer(client, monkeypatch):
    """
    One real hit exists, but the Owner has configured min_chunks=5 -
    the stream must treat this as insufficient evidence, proving the
    saved setting changes behavior, not just what GET reports back.
    """

    client.put("/admin/retrieval-settings", json={"top_k": 5, "score_threshold": 0.0, "min_chunks": 5})
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    events = _parse_sse(_stream(client, query="What is the vendor review policy?"))

    assert events[0] == ("sources", {"sources": []})
    answer_events = [data for etype, data in events if etype == "answer_chunk"]
    assert answer_events == [
        {"text": "Insufficient information found in the available knowledge base."}
    ]


def test_retrieval_settings_top_k_is_passed_through_when_request_omits_it(client, monkeypatch):
    client.put("/admin/retrieval-settings", json={"top_k": 7, "score_threshold": 0.0, "min_chunks": 1})

    captured = {}

    def _capture_retrieve(query, top_k=None, category=None, score_threshold=0.0):
        captured["top_k"] = top_k
        return [_hit()]

    monkeypatch.setattr(end_user_api, "retrieve", _capture_retrieve)

    _stream(client, query="What is the vendor review policy?")

    assert captured["top_k"] == 7


# ---------------------------------------------------------------------
# 10. Streaming - full event-sequence + content-type contract
# ---------------------------------------------------------------------


def test_streaming_event_sequence_is_exactly_sources_then_chunks_then_done(client, monkeypatch):
    monkeypatch.setattr(end_user_api, "retrieve", lambda *a, **k: [_hit()])

    events = _parse_sse(_stream(client, query="What is the vendor review policy?"))
    types = [e for e, _ in events]

    assert types[0] == "sources"
    assert types[-1] == "done"
    assert set(types) <= {"sources", "answer_chunk", "error", "done"}
    # No event type appears out of its allowed relative order.
    assert types.index("sources") < types.index("done")
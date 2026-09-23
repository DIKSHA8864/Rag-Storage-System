"""
Tests for Step 22's Research Observability gap fix -
app/analysis/answer_generation.py's stream_grounded_answer() now logs
one row per query (query text, retrieved chunk ids/scores, model,
token usage, latency, citation-check result) to the SAME llm_usage_log
table app/observability/usage_log.py's track_llm_call() already writes
to - not a second logging system. Owner research, Matter research, and
End User Q&A all share this one implementation (see
app/api/storage_api.py, app/api/end_user_api.py), so proving it here
proves it for all three call sites.
"""

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.analysis.answer_generation import stream_grounded_answer
from app.metadata.sqlite_repository import SQLiteMetadataRepository


@pytest.fixture(autouse=True)
def repo(tmp_path, monkeypatch):
    from app.api import storage_api

    repository = SQLiteMetadataRepository(tmp_path / "metadata.db")
    monkeypatch.setattr(storage_api, "metadata_repository", repository)
    return repository


@dataclass
class _FakeSettings:
    narrative_provider: str = "claude"
    anthropic_api_key: str = "test-key"
    analysis_model: str = "claude-opus-5"


def _chunks() -> list[dict]:
    return [
        {
            "chunk_id": "c-1", "filename": "policy.pdf", "category": "Docs",
            "chunk_text": "Vendor contracts require annual review.",
            "section": "1.1", "start_page": 1, "end_page": 1, "final_score": 0.87,
        }
    ]


class _FakeAsyncMessages:
    def __init__(self, response_text=None, error=None, input_tokens=42, output_tokens=17):
        self._response_text = response_text
        self._error = error
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    async def create(self, **kwargs):
        if self._error is not None:
            raise self._error
        block = SimpleNamespace(type="text", text=self._response_text)
        usage = SimpleNamespace(input_tokens=self._input_tokens, output_tokens=self._output_tokens)
        return SimpleNamespace(content=[block], usage=usage)


def _fake_async_anthropic(**kwargs):
    fake_messages = _FakeAsyncMessages(**kwargs)

    class _FakeAsyncAnthropic:
        def __init__(self, api_key=None):
            self.messages = fake_messages

    return _FakeAsyncAnthropic


def _drain(query: str, chunks: list[dict], min_chunks: int = 1, **kwargs) -> list[tuple[str, dict]]:
    async def _collect():
        return [event async for event in stream_grounded_answer(query, chunks, min_chunks, **kwargs)]

    return asyncio.run(_collect())


def _latest_log_row(repo) -> dict:
    with repo._connect() as conn:
        row = conn.execute("SELECT * FROM llm_usage_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None, "expected stream_grounded_answer() to have written a llm_usage_log row"
    return dict(row)


def test_grounded_claude_answer_logs_query_chunks_model_tokens_and_grounded_result(monkeypatch, repo):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_async_anthropic(response_text="Answer [policy.pdf]."))

    _drain("What is the vendor review policy?", _chunks(), purpose="owner_research")

    row = _latest_log_row(repo)
    assert row["purpose"] == "owner_research"
    assert row["query_text"] == "What is the vendor review policy?"
    assert json.loads(row["retrieved_chunk_ids"]) == ["c-1"]
    assert json.loads(row["retrieved_chunk_scores"]) == [0.87]
    assert row["model"] == "claude-opus-5"
    assert row["input_tokens"] == 42
    assert row["output_tokens"] == 17
    assert row["citation_check_result"] == "grounded"
    assert row["latency_ms"] >= 0


def test_fabricated_citation_logs_fabricated_discarded(monkeypatch, repo):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        _fake_async_anthropic(response_text="According to [not-a-real-file.pdf], vendors must comply."),
    )

    _drain("What is the vendor review policy?", _chunks())

    row = _latest_log_row(repo)
    assert row["citation_check_result"] == "fabricated_discarded"
    # The Claude call still happened and its (unused) token usage is still logged.
    assert row["model"] == "claude-opus-5"


def test_claude_error_logs_claude_error_fallback(monkeypatch, repo):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_async_anthropic(error=RuntimeError("simulated failure")))

    _drain("What is the vendor review policy?", _chunks())

    row = _latest_log_row(repo)
    assert row["citation_check_result"] == "claude_error_fallback"


def test_template_only_path_logs_template_only(monkeypatch, repo):
    monkeypatch.setattr(
        "app.analysis.answer_generation.get_settings",
        lambda: _FakeSettings(narrative_provider="template"),
    )

    _drain("What is the vendor review policy?", _chunks())

    row = _latest_log_row(repo)
    assert row["citation_check_result"] == "template_only"
    assert row["model"] == "template"
    assert row["input_tokens"] == 0
    assert row["output_tokens"] == 0


def test_insufficient_evidence_logs_without_calling_claude(monkeypatch, repo):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())

    _drain("What is the vendor review policy?", [], min_chunks=1)

    row = _latest_log_row(repo)
    assert row["citation_check_result"] == "insufficient_evidence"
    assert row["query_text"] == "What is the vendor review policy?"
    assert json.loads(row["retrieved_chunk_ids"]) == []


def test_matter_id_and_purpose_are_recorded_for_matter_research(monkeypatch, repo):
    monkeypatch.setattr(
        "app.analysis.answer_generation.get_settings",
        lambda: _FakeSettings(narrative_provider="template"),
    )

    _drain("What did the court order?", _chunks(), purpose="matter_research", matter_id=7, intake_session_id=3)

    row = _latest_log_row(repo)
    assert row["purpose"] == "matter_research"
    assert row["matter_id"] == 7
    assert row["intake_session_id"] == 3


def test_default_purpose_when_caller_omits_it(monkeypatch, repo):
    monkeypatch.setattr(
        "app.analysis.answer_generation.get_settings",
        lambda: _FakeSettings(narrative_provider="template"),
    )

    _drain("A query", _chunks())

    row = _latest_log_row(repo)
    assert row["purpose"] == "grounded_answer"

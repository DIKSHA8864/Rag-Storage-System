"""
Tests for app/analysis/answer_generation.py's Claude-backed path
(_claude_full_answer/generate_answer_stream) - the Anthropic client is
mocked throughout (no real API calls, no billing, no API key needed to
run these), same approach as tests/test_claude_narrative.py.

Covers the Phase 2 gaps the E2E audit found:
- the Claude-backed /ask generation path had zero coverage at all
  (tests/test_e2e_phase2.py only ever exercises the template
  fallback, since NARRATIVE_PROVIDER defaults to "template");
- "fabricated citation" was asserted only against the template path,
  which is safe by construction and can't actually demonstrate
  enforcement - test_generate_answer_stream_falls_back_to_template_when_citation_is_fabricated
  proves the real technical guard added to answer_generation.py
  (_citations_are_grounded) actually catches and discards a
  hallucinated citation instead of letting it reach the client;
- the active prompt version (app/prompts.py, PUT /admin/prompts) was
  never proven to actually reach the Claude call.
"""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.analysis.answer_generation import _template_answer, generate_answer_stream
from app.metadata.sqlite_repository import SQLiteMetadataRepository


@pytest.fixture(autouse=True)
def repo(tmp_path, monkeypatch):
    """
    generate_answer_stream() -> _claude_full_answer() reads
    storage_api.metadata_repository (app/prompts.py's get_active_prompt) -
    isolate it to a throwaway SQLite database for every test in this
    file, the same fix applied to tests/test_claude_narrative.py, so
    nothing here can touch the real project database/metadata.db.
    """

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
            "filename": "policy.pdf",
            "category": "Docs",
            "chunk_text": "Vendor contracts require annual review.",
            "section": "1.1",
            "start_page": 1,
            "end_page": 1,
        }
    ]


class _FakeAsyncMessages:
    def __init__(self, response_text: str | None = None, error: Exception | None = None):
        self._response_text = response_text
        self._error = error
        self.last_call: dict | None = None

    async def create(self, **kwargs):
        self.last_call = kwargs
        if self._error is not None:
            raise self._error
        block = SimpleNamespace(type="text", text=self._response_text)
        return SimpleNamespace(content=[block])


def _fake_async_anthropic(response_text: str | None = None, error: Exception | None = None):
    """Returns (fake_client_class, fake_messages) - fake_messages.last_call captures the create() kwargs."""

    fake_messages = _FakeAsyncMessages(response_text=response_text, error=error)

    class _FakeAsyncAnthropic:
        def __init__(self, api_key=None):
            self.messages = fake_messages

    return _FakeAsyncAnthropic, fake_messages


def _run_stream(query: str, chunks: list[dict]) -> str:
    async def _collect() -> str:
        return "".join([piece async for piece in generate_answer_stream(query, chunks)])

    return asyncio.run(_collect())


# ---------------------------------------------------------------------
# 1. The Claude-backed path actually runs and its output reaches the client
# ---------------------------------------------------------------------


def test_generate_answer_stream_uses_claude_when_citations_are_grounded(monkeypatch):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())

    grounded_text = "Vendor contracts require annual review [policy.pdf]."
    fake_client_cls, fake_messages = _fake_async_anthropic(response_text=grounded_text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    result = _run_stream("What is the vendor review policy?", _chunks())

    assert fake_messages.last_call is not None  # proves the real Claude path executed
    assert "Vendor contracts require annual review" in result
    assert "[policy.pdf]" in result


def test_generate_answer_stream_uses_template_when_provider_is_not_claude(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.answer_generation.get_settings",
        lambda: _FakeSettings(narrative_provider="template"),
    )

    result = _run_stream("What is the vendor review policy?", _chunks())

    assert result.strip() == _template_answer(_chunks()).strip()


# ---------------------------------------------------------------------
# 2/3. Technical citation enforcement - a fabricated citation is
# detected and discarded, not just discouraged by a prompt instruction.
# ---------------------------------------------------------------------


def test_generate_answer_stream_falls_back_to_template_when_citation_is_fabricated(monkeypatch):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())

    fabricated_text = "According to [not-a-real-file.pdf], vendors must comply with the policy."
    fake_client_cls, fake_messages = _fake_async_anthropic(response_text=fabricated_text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    result = _run_stream("What is the vendor review policy?", _chunks())

    # The fabricated text must never reach the client...
    assert "not-a-real-file.pdf" not in result
    assert fabricated_text not in result
    # ...it's discarded entirely, falling back to the grounded template answer.
    assert result.strip() == _template_answer(_chunks()).strip()


def test_generate_answer_stream_accepts_a_citation_with_a_section_suffix(monkeypatch):
    """
    _citations_are_grounded() tolerates "[filename - section]", not
    just a bare filename - Claude was shown "[policy.pdf - 1.1]" as
    the excerpt's label and may copy it verbatim rather than trimming
    it, and that must not be mistaken for a fabricated citation.
    """

    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())

    grounded_text = "Vendor contracts require annual review [policy.pdf - 1.1]."
    fake_client_cls, fake_messages = _fake_async_anthropic(response_text=grounded_text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    result = _run_stream("What is the vendor review policy?", _chunks())

    assert "[policy.pdf - 1.1]" in result


def test_generate_answer_stream_falls_back_to_template_on_claude_error(monkeypatch):
    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())

    fake_client_cls, fake_messages = _fake_async_anthropic(error=RuntimeError("simulated API error"))
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    result = _run_stream("What is the vendor review policy?", _chunks())

    assert result.strip() == _template_answer(_chunks()).strip()


# ---------------------------------------------------------------------
# 5. The Owner's active prompt version actually reaches the Claude call
# ---------------------------------------------------------------------


def test_claude_generation_uses_the_active_answer_system_prompt_version(monkeypatch, repo):
    repo.create_prompt_version("answer_system_prompt", "CUSTOM ANSWER PROMPT.", created_by="owner@example.com")

    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())
    fake_client_cls, fake_messages = _fake_async_anthropic(response_text="Answer [policy.pdf].")
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    _run_stream("What is the vendor review policy?", _chunks())

    assert fake_messages.last_call["system"] == "CUSTOM ANSWER PROMPT."


def test_claude_generation_uses_the_default_prompt_when_no_version_saved(monkeypatch):
    from app.analysis.answer_generation import _DEFAULT_ANSWER_SYSTEM_PROMPT

    monkeypatch.setattr("app.analysis.answer_generation.get_settings", lambda: _FakeSettings())
    fake_client_cls, fake_messages = _fake_async_anthropic(response_text="Answer [policy.pdf].")
    monkeypatch.setattr("anthropic.AsyncAnthropic", fake_client_cls)

    _run_stream("What is the vendor review policy?", _chunks())

    assert fake_messages.last_call["system"] == _DEFAULT_ANSWER_SYSTEM_PROMPT

"""
Tests for app/analysis/relevance_guard.py's filter_materially_relevant_chunks()
- the legal-issue relevance gate that stops app/analysis/answer_generation.py's
stream_grounded_answer() from treating a chunk that merely shares
vocabulary with the question (an unrelated CGL/D&O/Workers' Comp/
defamation document, say) as supporting evidence.

The Anthropic client is mocked throughout (same pattern as
tests/test_claude_narrative.py) - no real API key/call needed.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.analysis.relevance_guard import RelevanceCheckUnavailable, filter_materially_relevant_chunks


@pytest.fixture(autouse=True)
def _isolated_metadata_repository(tmp_path, monkeypatch):
    """filter_materially_relevant_chunks() logs usage via track_llm_call() - same isolation as tests/test_claude_narrative.py."""

    from app.api import storage_api
    from app.metadata.sqlite_repository import SQLiteMetadataRepository

    monkeypatch.setattr(
        storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db")
    )


@dataclass
class _FakeSettings:
    anthropic_api_key: str = "test-key"
    analysis_model: str = "claude-opus-5"


def _chunk(filename: str, text: str) -> dict:
    return {"chunk_id": filename, "filename": filename, "chunk_text": text, "final_score": 0.5}


def _fake_client(response_text: str, stop_reason: str = "end_turn"):
    block = SimpleNamespace(type="text", text=response_text)
    usage = SimpleNamespace(input_tokens=12, output_tokens=8)
    response = SimpleNamespace(content=[block], usage=usage, stop_reason=stop_reason)

    class _FakeMessages:
        def create(self, **kwargs):
            _FakeMessages.last_call = kwargs
            return response

    return SimpleNamespace(messages=_FakeMessages())


def _employment_and_insurance_chunks() -> list[dict]:
    return [
        _chunk(
            "employment_handbook.pdf",
            "Employees may file a complaint of discrimination with HR within 30 days of the alleged conduct.",
        ),
        _chunk(
            "cgl_policy_exclusions.pdf",
            "This CGL policy excludes claims arising from employment-related practices including termination, "
            "discrimination, and harassment complaints brought by an employee against the insured.",
        ),
    ]


def test_no_api_key_is_a_no_op(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.relevance_guard.get_settings", lambda: _FakeSettings(anthropic_api_key="")
    )

    chunks = _employment_and_insurance_chunks()
    result = filter_materially_relevant_chunks("Can an employee be fired for filing a discrimination complaint?", chunks)

    assert result == chunks


def test_empty_chunks_returns_empty_without_calling_claude(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    calls = []
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: calls.append(1) or _fake_client("[]"))

    result = filter_materially_relevant_chunks("Any question", [])

    assert result == []
    assert calls == []


def test_keeps_only_the_index_claude_marks_materially_relevant(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client("[0]"))

    chunks = _employment_and_insurance_chunks()
    result = filter_materially_relevant_chunks(
        "Can an employee be fired for filing a discrimination complaint?", chunks
    )

    assert result == [chunks[0]]


def test_returns_every_chunk_flagged_relevant_in_order(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client("[0, 1]"))

    chunks = _employment_and_insurance_chunks()
    result = filter_materially_relevant_chunks("A question both chunks address", chunks)

    assert result == chunks


def test_empty_json_array_response_means_no_authority_found(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client("[]"))

    result = filter_materially_relevant_chunks(
        "Can an employee be fired for filing a discrimination complaint?", _employment_and_insurance_chunks()
    )

    assert result == []


def test_fails_closed_on_unparseable_response(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client("I think excerpt 0 is relevant."))

    with pytest.raises(RelevanceCheckUnavailable):
        filter_materially_relevant_chunks("A question", _employment_and_insurance_chunks())


def test_fails_closed_when_response_is_not_a_json_array(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client('{"0": true}'))

    with pytest.raises(RelevanceCheckUnavailable):
        filter_materially_relevant_chunks("A question", _employment_and_insurance_chunks())


def test_fails_closed_on_api_error(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())

    class _BrokenMessages:
        def create(self, **kwargs):
            raise RuntimeError("network error")

    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: SimpleNamespace(messages=_BrokenMessages()))

    with pytest.raises(RelevanceCheckUnavailable):
        filter_materially_relevant_chunks("A question", _employment_and_insurance_chunks())


def test_out_of_range_indices_are_ignored_not_treated_as_a_parse_failure(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client("[0, 99]"))

    chunks = _employment_and_insurance_chunks()
    result = filter_materially_relevant_chunks("A question", chunks)

    assert result == [chunks[0]]


def test_sends_the_question_and_chunk_text_to_claude(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    fake_client = _fake_client("[0]")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    chunks = _employment_and_insurance_chunks()
    filter_materially_relevant_chunks("Can an employee be fired for filing a discrimination complaint?", chunks)

    sent_message = fake_client.messages.last_call["messages"][0]["content"]
    assert "Can an employee be fired for filing a discrimination complaint?" in sent_message
    assert "employment_handbook.pdf" in sent_message
    assert "cgl_policy_exclusions.pdf" in sent_message


def test_structured_output_shape_is_parsed(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client('{"relevant_excerpts": [1]}'))

    chunks = _employment_and_insurance_chunks()
    assert filter_materially_relevant_chunks("A question", chunks) == [chunks[1]]


def test_leaves_room_for_thinking_and_requests_json_schema_output(monkeypatch):
    """Regression: a 200-token cap was all spent on adaptive thinking, so no verdict came back -> every Ask said 'No authority'."""

    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    fake_client = _fake_client('{"relevant_excerpts": [0]}')
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: fake_client)

    filter_materially_relevant_chunks("A question", _employment_and_insurance_chunks())

    call = fake_client.messages.last_call
    assert call["max_tokens"] >= 2000
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"]["required"] == ["relevant_excerpts"]


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_a_cut_short_verdict_is_unavailable_not_an_empty_verdict(monkeypatch, stop_reason):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client("", stop_reason=stop_reason))

    with pytest.raises(RelevanceCheckUnavailable):
        filter_materially_relevant_chunks("A question", _employment_and_insurance_chunks())


def test_boolean_indices_are_rejected(monkeypatch):
    monkeypatch.setattr("app.analysis.relevance_guard.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: _fake_client('{"relevant_excerpts": [true]}'))

    with pytest.raises(RelevanceCheckUnavailable):
        filter_materially_relevant_chunks("A question", _employment_and_insurance_chunks())

"""
Tests for ClaudeNarrativeGenerator (app/analysis/claude_narrative.py) -
the Anthropic client itself is mocked throughout (no real API calls,
no API key needed to run these), covering: prompt/response wiring,
malformed-response handling, and the missing-API-key guard. Real
end-to-end Claude behavior needs ANTHROPIC_API_KEY and isn't exercised
by the automated suite - see app/analysis/report_builder.py's fallback
to TemplateNarrativeGenerator for what happens if this provider
misbehaves in production.
"""

import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.analysis.claude_narrative import ClaudeNarrativeGenerator
from app.analysis.models import ComparisonItem, ComparisonResult, SourceEvidence
from app.metadata.sqlite_repository import SQLiteMetadataRepository


@pytest.fixture(autouse=True)
def _isolated_metadata_repository(tmp_path, monkeypatch):
    """
    generate() reads storage_api.metadata_repository (app/prompts.py's
    get_active_prompt(), for the "narrative_system_prompt" version) -
    without this, these tests fall through to the real module-level
    singleton and touch the actual project database/metadata.db, the
    same isolation every other test file in this suite already gets
    via its own `client`/`repo` fixture.
    """

    from app.api import storage_api

    monkeypatch.setattr(
        storage_api, "metadata_repository", SQLiteMetadataRepository(tmp_path / "metadata.db")
    )


@dataclass
class _FakeSettings:
    anthropic_api_key: str = "test-key"
    analysis_model: str = "claude-opus-5"


def _comparison() -> ComparisonResult:
    item = ComparisonItem(
        input_chunk_index=0,
        input_text="Vendor contracts must be reviewed annually.",
        classification="match",
        top_score=0.9,
        sources=[
            SourceEvidence(
                filename="policy.pdf", category="Docs", document_id="policy", chunk_id="c-1",
                chunk_text="Contracts are reviewed every year.", chapter=None, section="1.1",
                start_page=1, end_page=1, score=0.9,
            )
        ],
    )
    return ComparisonResult(items=[item], coverage_ratio=1.0, avg_confidence=0.9, overall_match_score=90.0)


def _fake_client(response_text: str):
    block = SimpleNamespace(type="text", text=response_text)
    response = SimpleNamespace(content=[block])

    class _FakeMessages:
        def create(self, **kwargs):
            _FakeMessages.last_call = kwargs
            return response

    return SimpleNamespace(messages=_FakeMessages())


def test_generate_parses_well_formed_response(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.claude_narrative.get_settings", lambda: _FakeSettings()
    )

    valid_json = json.dumps(
        {
            "executive_summary": "One paragraph summary.",
            "item_narratives": {"0": "Closely matches policy.pdf section 1.1."},
            "recommendations": [],
        }
    )
    monkeypatch.setattr(
        "app.analysis.claude_narrative.anthropic.Anthropic",
        lambda api_key: _fake_client(valid_json),
    )

    generator = ClaudeNarrativeGenerator()
    result = generator.generate(_comparison())

    assert result.executive_summary == "One paragraph summary."
    assert result.item_narratives[0] == "Closely matches policy.pdf section 1.1."
    assert result.recommendations == []


def test_generate_raises_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.claude_narrative.get_settings", lambda: _FakeSettings()
    )
    monkeypatch.setattr(
        "app.analysis.claude_narrative.anthropic.Anthropic",
        lambda api_key: _fake_client("not json"),
    )

    generator = ClaudeNarrativeGenerator()

    with pytest.raises(RuntimeError, match="not valid JSON"):
        generator.generate(_comparison())


def test_generate_raises_on_missing_keys(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.claude_narrative.get_settings", lambda: _FakeSettings()
    )
    monkeypatch.setattr(
        "app.analysis.claude_narrative.anthropic.Anthropic",
        lambda api_key: _fake_client(json.dumps({"executive_summary": "only this"})),
    )

    generator = ClaudeNarrativeGenerator()

    with pytest.raises(RuntimeError, match="unexpected shape"):
        generator.generate(_comparison())


def test_constructor_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.claude_narrative.get_settings",
        lambda: _FakeSettings(anthropic_api_key=""),
    )

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeNarrativeGenerator()

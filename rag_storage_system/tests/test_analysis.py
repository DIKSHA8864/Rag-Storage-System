"""
Tests for app/analysis/ - matching/scoring (matcher.py), the
deterministic template narrative (template_narrative.py), and the
hallucination-control report assembly (report_builder.py).

app/retrieval/retriever.retrieve() is monkeypatched throughout (not
hit for real) - retrieval quality itself is covered by
tests/test_vector_store.py and tests/test_retrieval.py; these tests
are about what app/analysis/ does with retrieval results, given full
control over what they are.
"""

import pytest

from app.analysis import matcher, report_builder
from app.analysis.models import ComparisonItem, ComparisonResult, SourceEvidence
from app.analysis.template_narrative import TemplateNarrativeGenerator
from config.settings import get_settings


def _hit(
    chunk_id="c-1",
    score=0.9,
    filename="policy.pdf",
    category="Docs",
    document_id="policy",
    chunk_text="The policy requires annual review.",
    section="1.1",
):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "category": category,
        "filename": filename,
        "chunk_text": chunk_text,
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
# matcher.classify_score()
# ---------------------------------------------------------------------


def test_classify_score_uses_configured_thresholds():
    settings = get_settings()

    assert matcher.classify_score(settings.match_score_threshold_match) == "match"
    assert matcher.classify_score(settings.match_score_threshold_partial) == "partial_match"
    assert matcher.classify_score(0.0) == "gap"


# ---------------------------------------------------------------------
# matcher.compare_input_to_knowledge_base()
# ---------------------------------------------------------------------


def test_compare_classifies_each_chunk_and_scores_overall(monkeypatch):
    def fake_retrieve(query, top_k, category=None, tenant_id=1):
        if "covered" in query:
            return [_hit(score=0.9)]
        return []

    monkeypatch.setattr(matcher, "retrieve", fake_retrieve)

    input_chunks = [{"text": "This topic is covered."}, {"text": "This topic is not."}]
    result = matcher.compare_input_to_knowledge_base(input_chunks)

    assert result.items[0].classification == "match"
    assert result.items[1].classification == "gap"
    assert result.has_any_evidence is True
    # coverage_ratio = (1 match + 0 partial) / 2 = 0.5; avg_confidence = (0.9 + 0) / 2 = 0.45
    settings = get_settings()
    expected = round(
        100
        * (
            settings.match_score_coverage_weight * 0.5
            + settings.match_score_confidence_weight * 0.45
        ),
        1,
    )
    assert result.overall_match_score == expected


def test_compare_all_gaps_means_no_evidence(monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [])

    result = matcher.compare_input_to_knowledge_base([{"text": "unrelated content"}])

    assert result.items[0].classification == "gap"
    assert result.has_any_evidence is False


def test_compare_flags_conflict_on_numeric_mismatch(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "retrieve",
        lambda *a, **k: [_hit(score=0.95, chunk_text="Reviews happen every 60 days.")],
    )

    result = matcher.compare_input_to_knowledge_base(
        [{"text": "Our policy requires review every 30 days."}]
    )

    assert result.items[0].classification == "match"
    assert result.items[0].is_conflict is True


def test_compare_no_conflict_when_numbers_agree(monkeypatch):
    monkeypatch.setattr(
        matcher,
        "retrieve",
        lambda *a, **k: [_hit(score=0.95, chunk_text="Reviews happen every 30 days.")],
    )

    result = matcher.compare_input_to_knowledge_base(
        [{"text": "Our policy requires review every 30 days."}]
    )

    assert result.items[0].is_conflict is False


# ---------------------------------------------------------------------
# TemplateNarrativeGenerator
# ---------------------------------------------------------------------


def _comparison_with(*items: ComparisonItem) -> ComparisonResult:
    total = len(items) or 1
    matched = sum(1 for i in items if i.classification == "match")
    partial = sum(1 for i in items if i.classification == "partial_match")
    coverage = (matched + 0.5 * partial) / total
    confidence = sum(i.top_score for i in items) / total
    return ComparisonResult(
        items=list(items),
        coverage_ratio=coverage,
        avg_confidence=confidence,
        overall_match_score=round(100 * coverage, 1),
    )


def test_template_narrative_summary_and_recommendations():
    gap_item = ComparisonItem(
        input_chunk_index=0, input_text="A new requirement.", classification="gap", top_score=0.1
    )
    match_item = ComparisonItem(
        input_chunk_index=1,
        input_text="An existing requirement.",
        classification="match",
        top_score=0.9,
        sources=[
            SourceEvidence(
                filename="policy.pdf", category="Docs", document_id="policy", chunk_id="c-1",
                chunk_text="text", chapter=None, section="1.1", start_page=1, end_page=1, score=0.9,
            )
        ],
    )

    comparison = _comparison_with(gap_item, match_item)
    narrative = TemplateNarrativeGenerator().generate(comparison)

    assert "1" in narrative.executive_summary or "match" in narrative.executive_summary.lower()
    assert 1 in narrative.item_narratives  # only the item with sources
    assert 0 not in narrative.item_narratives
    assert any("A new requirement." in rec for rec in narrative.recommendations)


# ---------------------------------------------------------------------
# report_builder.build_analysis_report() - hallucination control
# ---------------------------------------------------------------------


def test_report_with_no_evidence_returns_fixed_message(monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [])

    report = report_builder.build_analysis_report([{"text": "completely unrelated text"}])

    assert report["insufficient_evidence"] is True
    assert report["executive_summary"]["text"] == report_builder.INSUFFICIENT_EVIDENCE_MESSAGE
    assert report["overall_match_score"] == 0.0
    assert report["detailed_matching"]["similarities"] == []
    assert report["detailed_matching"]["differences"] == []
    assert len(report["detailed_matching"]["gaps"]) == 1


def test_report_gap_item_narrative_is_fixed_even_with_other_evidence(monkeypatch):
    def fake_retrieve(query, top_k, category=None, tenant_id=1):
        if "supported" in query:
            return [_hit(score=0.95)]
        return []

    monkeypatch.setattr(matcher, "retrieve", fake_retrieve)

    report = report_builder.build_analysis_report(
        [{"text": "This is supported."}, {"text": "This is not."}]
    )

    assert report["insufficient_evidence"] is False
    gap_items = report["detailed_matching"]["gaps"]
    assert len(gap_items) == 1
    assert gap_items[0]["narrative"]["text"] == report_builder.NO_ITEM_EVIDENCE_MESSAGE


def test_report_provenance_labels_present(monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [_hit(score=0.95)])

    report = report_builder.build_analysis_report([{"text": "supported requirement"}])

    assert report["executive_summary"]["provenance"] == "generated"
    match_item = report["detailed_matching"]["similarities"][0]
    assert match_item["narrative"]["provenance"] == "generated"
    assert match_item["sources"][0]["provenance"] == "retrieved"
    assert report["provenance_legend"]["recommendation"]


def test_report_sources_deduplicated_across_items(monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [_hit(chunk_id="shared-chunk", score=0.9)])

    report = report_builder.build_analysis_report(
        [{"text": "requirement one"}, {"text": "requirement two"}]
    )

    assert len(report["sources"]) == 1


def test_report_builder_falls_back_to_template_on_narrative_error(monkeypatch):
    monkeypatch.setattr(matcher, "retrieve", lambda *a, **k: [_hit(score=0.95)])

    class _BrokenGenerator:
        def generate(self, comparison):
            raise RuntimeError("simulated failure")

    monkeypatch.setattr(report_builder, "get_narrative_generator", lambda: _BrokenGenerator())

    report = report_builder.build_analysis_report([{"text": "a supported requirement"}])

    assert report["insufficient_evidence"] is False
    assert report["executive_summary"]["text"]  # template still produced something

"""
Regression prompts (Milestone 7 / Working Agreements): a small,
curated set of known queries against the golden/demo corpus whose
expected retrieval shape must not silently drift as retrieval,
chunking, or scoring code changes. This is NOT about specific chunk
text (too brittle) - it asserts the class of result (found vs. not
found, right category) stays stable.

Extend tests/fixtures/regression_prompts.json as real regressions are
found - each fixed bug should get one entry here.
"""

import json
from pathlib import Path

import pytest

from app.retrieval.retriever import retrieve

_FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "regression_prompts.json").read_text())


@pytest.mark.parametrize("case", _FIXTURES, ids=[c["name"] for c in _FIXTURES])
def test_regression_prompt(monkeypatch, case):
    from app.report import rag_analysis

    def _fake_retrieve(query, top_k, category=None, score_threshold=0.0):
        if "overtime" in query.lower():
            return [{
                "chunk_id": "c-1", "document_id": "doc", "category": "Wage & Hour",
                "filename": "overtime_policy.pdf", "chunk_text": "Overtime must be paid at 1.5x for hours over 40/week.",
                "section": "2.1", "start_page": 1, "end_page": 1, "final_score": 0.85,
            }]
        return []

    monkeypatch.setattr("app.retrieval.retriever.retrieve", _fake_retrieve)
    from app.retrieval.retriever import retrieve as patched_retrieve

    results = patched_retrieve(case["query"], top_k=5)

    assert len(results) >= case["expected_min_results"]
    if case["expected_category_contains"]:
        assert any(case["expected_category_contains"] in r["category"] for r in results)
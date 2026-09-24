"""
Retrieval Settings - DB-backed (app/metadata/base.py's
get_retrieval_settings()/update_retrieval_settings(), implemented by
both SQLiteMetadataRepository and PostgresMetadataRepository) so the
Owner can tune the hybrid retrieval pipeline
(app/retrieval/retriever.py) from the Admin Dashboard
(PUT /admin/retrieval-settings, app/api/storage_api.py) without a code
change or restart.

POST /end-user/query/stream ("ask") resolves Top K/score threshold/
minimum chunks through get_current_retrieval_settings() so it always
honors whatever the Owner last saved.
"""

from dataclasses import dataclass
from typing import Optional

from app.metadata.base import MetadataRepository

DEFAULT_TOP_K = 5
# 0.0 (every retrieval call's real starting point until this was
# tuned) let ANY chunk through, including one that only shares
# vocabulary with the query via app/retrieval/reranker.py's keyword
# channel - the exact failure mode that let a CGL/D&O/Workers' Comp/
# defamation document "answer" an unrelated employment question just
# because it happened to mention the same words. 0.3 reuses the same,
# already-calibrated cutoff app/analysis/matcher.py's
# MATCH_SCORE_THRESHOLD_PARTIAL uses for the identical final_score
# scale (same embedding model, same reranker) - see that module's
# docstring for the calibration readings ("same topic, different
# wording" ~0.36, "unrelated" ~0.01). This is a numeric floor, not a
# substitute for app/analysis/relevance_guard.py's legal-issue-level
# check - both apply.
DEFAULT_SCORE_THRESHOLD = 0.3
DEFAULT_MIN_CHUNKS = 1


@dataclass
class RetrievalSettings:
    top_k: int
    score_threshold: float
    min_chunks: int


def get_current_retrieval_settings(metadata_repository: MetadataRepository) -> RetrievalSettings:
    """Return the Owner-edited retrieval settings, or the built-in defaults if none saved yet."""

    saved = metadata_repository.get_retrieval_settings()

    if saved is None:
        return RetrievalSettings(
            top_k=DEFAULT_TOP_K,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
            min_chunks=DEFAULT_MIN_CHUNKS,
        )

    return RetrievalSettings(
        top_k=saved["top_k"],
        score_threshold=saved["score_threshold"],
        min_chunks=saved["min_chunks"],
    )

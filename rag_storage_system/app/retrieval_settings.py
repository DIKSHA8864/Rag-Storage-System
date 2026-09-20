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
DEFAULT_SCORE_THRESHOLD = 0.0
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

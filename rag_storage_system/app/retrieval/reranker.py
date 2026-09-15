"""
Reranking - the last stage of app/retrieval/retriever.py's hybrid
pipeline. Vector search and keyword search each return their own
chunks with their own, differently-scaled scores (cosine similarity
vs. a Postgres ts_rank), so a chunk found by only one of them can't be
compared to one found by both just by looking at either raw score.

This is a simple weighted fusion, not a learned/cross-encoder
reranker - fine as a first pass (a real cross-encoder model can slot
in behind rerank() later without changing its signature or callers).

IMPORTANT: scores are put on a comparable [0, 1] scale using a FIXED
transform, never per-query min-max normalization. Min-max would rescale
whatever range showed up in one query's candidate set to fill [0, 1] -
so the single best-of-a-bad-lot candidate always ends up looking like
a perfect match (score 1.0), even when every candidate is a poor match
in absolute terms. That's fatal for anything that treats final_score
as an absolute relevance/confidence signal - which
app/analysis/matcher.py does, to decide whether a claim has real
knowledge-base support at all (see its MATCH_SCORE_THRESHOLD_* guard).
Cosine similarity is already a meaningful absolute scale, so it's used
as-is; ts_rank isn't, so it gets a fixed (not per-query) saturating
scale instead - see KEYWORD_SCORE_SCALE below.
"""

VECTOR_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4

# ts_rank has no fixed upper bound, but in practice sits well under 1.0
# for real queries against chunk-sized text - a rank at or above this
# is treated as "fully confident" keyword support. Tune this constant,
# not per-query normalization, if keyword scores start looking mis-scaled.
KEYWORD_SCORE_SCALE = 0.3


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _vector_confidence(raw_cosine_similarity: float) -> float:
    """Cosine similarity is already meaningfully scaled - just clamp float noise into [0, 1]."""

    return _clamp(raw_cosine_similarity)


def _keyword_confidence(raw_ts_rank: float) -> float:
    """Fixed saturating scale, not per-query min-max - see this module's docstring."""

    return _clamp(raw_ts_rank / KEYWORD_SCORE_SCALE)


def rerank(vector_hits: list[dict], keyword_hits: list[dict], top_k: int = 5) -> list[dict]:
    """
    Merge vector_search() and keyword_search() results (each a list of
    dicts with at least chunk_id/score/chunk_text/...) into one
    ranked list of at most top_k chunks.

    A chunk found by both signals outranks one found by only one,
    all else equal - that agreement is exactly what hybrid search is
    for: catching what plain vector similarity alone would miss (or
    demoting a coincidental near-neighbor keyword search doesn't
    corroborate at all).
    """

    merged: dict[str, dict] = {}

    for hit in vector_hits:
        merged[hit["chunk_id"]] = {
            **hit,
            "vector_score": _vector_confidence(hit["score"]),
            "keyword_score": 0.0,
        }

    for hit in keyword_hits:
        keyword_score = _keyword_confidence(hit["score"])

        if hit["chunk_id"] in merged:
            merged[hit["chunk_id"]]["keyword_score"] = keyword_score
        else:
            merged[hit["chunk_id"]] = {**hit, "vector_score": 0.0, "keyword_score": keyword_score}

    for chunk in merged.values():
        chunk["final_score"] = (
            VECTOR_WEIGHT * chunk["vector_score"] + KEYWORD_WEIGHT * chunk["keyword_score"]
        )

    ranked = sorted(merged.values(), key=lambda chunk: chunk["final_score"], reverse=True)

    return ranked[:top_k]

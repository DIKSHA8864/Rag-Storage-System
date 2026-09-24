"""
Legal-issue relevance gate for Owner Research, Matter Research, and
End User Q&A (app/analysis/answer_generation.py's stream_grounded_answer()
- the one shared implementation all three use, so fixing it here fixes
all three at once).

THE PROBLEM THIS SOLVES: app/retrieval/reranker.py's final_score blends
vector similarity and keyword match. A chunk from an entirely
different kind of document - a CGL/D&O/Workers' Compensation insurance
policy, a defamation matter, anything - can still score moderately or
even highly if it happens to share vocabulary with the question
("employment", "termination", "discrimination", and "complaint" all
appear routinely in insurance exclusions clauses, for instance).
Sharing vocabulary (or even a moderate embedding similarity, since
embeddings capture topical/lexical closeness, not legal-domain
distinctions) is not the same thing as being about the same legal
issue. Retrieval optimizes for recall; this module is the precision
gate between retrieval and the answer generator, judging whether a
candidate chunk actually addresses the SAME legal issue as the
question - something a fixed score threshold cannot reliably do on its
own (see app/retrieval_settings.py's DEFAULT_SCORE_THRESHOLD for the
complementary, always-on numeric floor).

WHAT THIS NEVER DOES: it never adds a fact, a legal rule, or any text
to the eventual answer, and it is never given anything beyond the
question and the chunk text retrieval already found in the firm's own
library - no outside/public/generic model knowledge is ever
introduced. It only ever REMOVES chunks from the candidate set the
answer generator is given - the same "a guard may only subtract, never
add" principle app/analysis/answer_generation.py's
_citations_are_grounded() already applies to Claude's citations AFTER
generation; this is the same guarantee, applied to retrieval BEFORE
generation.

Requires ANTHROPIC_API_KEY (the same key NARRATIVE_PROVIDER=claude
already uses) to do real classification - without it, there is no
model available to reason about legal-issue-level relevance, so
filter_materially_relevant_chunks() is a no-op (chunks pass through
unfiltered) and app/retrieval_settings.py's raised score floor is the
only defense active. This mirrors how every other real-vs-mock
provider in this codebase (embeddings, narrative, vision, OCR, STT)
already degrades: never fabricate a capability that isn't configured.

FAILS CLOSED, not open: if Claude's classification response can't be
parsed, or the API call itself fails, this returns NO chunks as
verified-relevant (rather than treating the failure as "everything
passes") - for a legal-research tool, an honest gap is always
preferable to proceeding on unverified grounding.
"""

import json
import logging
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

_MAX_EXCERPT_CHARS = 600

_SYSTEM_PROMPT = """\
You are a retrieval-quality filter for a legal research tool, not a \
legal advisor. You will be given a legal QUESTION and a numbered list \
of excerpts retrieved from a law firm's own document library by \
keyword/vector search.

Retrieval sometimes surfaces excerpts that only share VOCABULARY with \
the question without actually addressing the same legal issue - for \
example, an insurance policy's exclusions clause that happens to \
mention "discrimination" or "termination" is NOT relevant to an \
employment discrimination question just because those words appear; \
a Workers' Compensation, CGL, D&O, or defamation document is NOT \
relevant to an unrelated employment question merely because of \
incidental keyword overlap.

For each excerpt, decide whether it is MATERIALLY relevant: does it \
actually address the same legal issue, claim, or subject matter as \
the QUESTION - not merely share words with it.

Respond with ONLY a JSON array of the integer indices of the excerpts \
that ARE materially relevant, e.g. [0, 2]. If none are materially \
relevant, respond with exactly []. Output nothing else - no \
explanation, no legal analysis, no additional text.
"""


def _build_user_message(query: str, chunks: list[dict]) -> str:
    excerpts = "\n\n".join(
        f"[{i}] (source: {chunk.get('filename', 'unknown')}): {chunk.get('chunk_text', '')[:_MAX_EXCERPT_CHARS]}"
        for i, chunk in enumerate(chunks)
    )
    return f"QUESTION:\n{query}\n\nEXCERPTS:\n{excerpts}"


def filter_materially_relevant_chunks(
    query: str, chunks: list[dict], tenant_id: int = 1
) -> list[dict]:
    """
    Returns the subset of `chunks` that materially address the same
    legal issue as `query`, preserving their original order and
    content unchanged - never reorders, rewrites, or augments them.

    A no-op (returns `chunks` unchanged) when ANTHROPIC_API_KEY isn't
    set, since there is then no way to perform real relevance
    classification - see this module's docstring.
    """

    if not chunks:
        return []

    settings = get_settings()
    if not settings.anthropic_api_key:
        return chunks

    import anthropic

    from app.observability.usage_log import track_llm_call

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        with track_llm_call("relevance_filter", settings.analysis_model, tenant_id=tenant_id) as record_usage:
            response = client.messages.create(
                model=settings.analysis_model,
                max_tokens=200,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_message(query, chunks)}],
            )
            usage = getattr(response, "usage", None)
            record_usage(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
    except Exception:
        logger.warning(
            "Relevance filtering failed (Claude call error) - treating no chunks as "
            "verified-relevant rather than risking an answer grounded in unverified sources.",
            exc_info=True,
        )
        return []

    relevant_indices = _parse_relevant_indices("".join(
        block.text for block in response.content if block.type == "text"
    ), len(chunks))

    if relevant_indices is None:
        logger.warning(
            "Relevance filtering got an unparseable response from Claude - treating no "
            "chunks as verified-relevant rather than risking an answer grounded in "
            "unverified sources."
        )
        return []

    return [chunk for i, chunk in enumerate(chunks) if i in relevant_indices]


def _parse_relevant_indices(text: str, chunk_count: int) -> Optional[set[int]]:
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list) or not all(isinstance(i, int) for i in parsed):
        return None

    return {i for i in parsed if 0 <= i < chunk_count}

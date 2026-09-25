"""
Grounded Q&A answer generation for POST /end-user/query/stream (see
app/api/end_user_api.py) - same hallucination-control philosophy as
app/analysis/template_narrative.py and claude_narrative.py: an answer
is built/generated ONLY from the chunks retrieval already found for
this exact request, never from outside knowledge.

CITATION LOCK: the caller (app/api/end_user_api.py) runs retrieval
exactly once and sends the resulting `sources` list to the client
BEFORE either generator below ever runs - both take that same,
already-final list of chunks and are never given a chance to fetch a
different one mid-stream, so the citations shown never drift from what
actually produced the streamed text.

CITATION ENFORCEMENT (Claude path only - the template path is
trivially grounded by construction, see _template_answer()): a system
prompt telling Claude not to invent a citation is an instruction, not
a guarantee - Claude is still free to ignore it. _citations_are_grounded()
technically checks every [bracketed] citation the generated text
contains against the locked chunk set, and generate_answer_stream()
discards the whole answer and falls back to the deterministic template
instead if even one citation is fabricated. This is why
_claude_full_answer() buffers Claude's full response rather than
token-streaming it live: once a token has gone out over the SSE
connection it can't be un-sent, so verifying citations is only
possible before the first byte reaches the client.

PROMPT-INJECTION RESISTANCE: retrieved chunk text and the caller's
`query` are only ever placed inside clearly delimited data blocks
(KNOWLEDGE BASE EXCERPTS: / QUESTION:), never concatenated into the
system instructions - text embedded in a client's uploaded document or
pasted query can only ever be interpreted as content to answer from,
never as an instruction to the model. Citation lock (see above) is the
backstop even if that boundary were somehow crossed: an ungrounded
citation is caught and discarded regardless of how it was produced.

RELEVANCE GATE (stream_grounded_answer(), before any of the above ever
runs): retrieval optimizes for recall, so its candidate chunks can
include one that only shares vocabulary with the question (a CGL/D&O/
Workers' Compensation/defamation document that happens to mention
"employment", "termination", "discrimination", or "complaint") without
addressing the same legal issue at all. app/analysis/relevance_guard.py's
filter_materially_relevant_chunks() removes those before the honest-gap
check, the locked `sources`, or generate_answer_stream() ever see
them - so a question with no materially relevant authority in the
library gets the honest-gap answer instead of one built from
loosely-related sources.
"""

import asyncio
import logging
import re
from typing import AsyncIterator

from config.settings import get_settings

logger = logging.getLogger(__name__)

_WORDS_PER_CHUNK = 6
_STREAM_DELAY_SECONDS = 0.03

_CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")

_DEFAULT_ANSWER_SYSTEM_PROMPT = (
    "Answer the user's question using ONLY the knowledge-base excerpts below. "
    "Never introduce outside knowledge or invented facts. If the excerpts don't "
    "fully answer the question, say what is and isn't supported. Keep the answer concise.\n\n"
    "CITATION FORMAT (required): every factual claim must be followed immediately "
    "by a bracketed citation naming its source, e.g. [policy.pdf] - copy the "
    "filename exactly from the bracketed label shown before that excerpt below. "
    "Never cite a filename that was not shown to you, and never invent a citation."
)


def _chunk_label(chunk: dict) -> str:
    location = chunk.get("section")
    if not location and chunk.get("start_page"):
        location = f"pp. {chunk['start_page']}-{chunk['end_page']}"
    return chunk["filename"] + (f" - {location}" if location else "")


def _template_answer(chunks: list[dict]) -> str:
    """
    Deterministic, no-API-key answer: the strongest supporting
    excerpt(s), each attributed to its source - same "never say more
    than the retrieved text supports" rule as TemplateNarrativeGenerator.
    Trivially grounded by construction (every citation it writes comes
    directly from `chunks`), unlike the Claude path below.
    """

    lines = [f"Based on {len(chunks)} matching section(s) of the knowledge base:"]

    for chunk in chunks:
        lines.append(f"- {chunk['chunk_text']} (source: '{_chunk_label(chunk)}')")

    return "\n".join(lines)


async def _stream_words(text: str) -> AsyncIterator[str]:
    words = text.split(" ")

    for i in range(0, len(words), _WORDS_PER_CHUNK):
        yield " ".join(words[i : i + _WORDS_PER_CHUNK]) + " "
        await asyncio.sleep(_STREAM_DELAY_SECONDS)


def _citations_are_grounded(text: str, allowed_filenames: set[str]) -> bool:
    """
    True only if every [bracketed] citation in `text` names a filename
    actually in `allowed_filenames` - the locked chunk set this
    request's retrieval found. Tolerant of a "[filename - section]"
    form too (only the part before " - " is compared), since an LLM
    won't always copy the bracketed label verbatim.
    """

    for raw_citation in _CITATION_PATTERN.findall(text):
        filename = raw_citation.split(" - ", 1)[0].strip()
        if filename not in allowed_filenames:
            return False

    return True


_ANSWER_MAX_TOKENS = 16000


async def _claude_full_answer(
    query: str, chunks: list[dict], usage_log: dict | None = None, tenant_id: int = 1
) -> str:
    """
    Runs the real Claude call and returns its full response text -
    buffered, not token-streamed, so generate_answer_stream() can
    citation-check it before any of it reaches the client (see this
    module's docstring for why that rules out live token streaming).

    `usage_log`, when passed, is filled in with the model name and
    token counts this call actually used - observability data for
    stream_grounded_answer()'s per-query log, never anything that
    changes the answer itself.
    """

    import anthropic

    from app.api import storage_api
    from app.prompts import get_active_prompt

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    context = "\n\n".join(f"[{_chunk_label(c)}]\n{c['chunk_text']}" for c in chunks)

    system_prompt = get_active_prompt(
        storage_api.metadata_repository, "answer_system_prompt", _DEFAULT_ANSWER_SYSTEM_PROMPT, tenant_id=tenant_id
    )

    response = await client.messages.create(
        model=settings.analysis_model,
        # Adaptive thinking is on by default on current Opus models and its
        # tokens count against this cap - too small a cap leaves a cut-off
        # or empty answer (checked below, never shown to the user).
        max_tokens=_ANSWER_MAX_TOKENS,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"KNOWLEDGE BASE EXCERPTS:\n{context}\n\nQUESTION:\n{query}"}
        ],
    )

    if usage_log is not None:
        usage_log["model"] = settings.analysis_model
        # getattr-guarded: token counts are observability data only -
        # a test double or an SDK response shape this code doesn't
        # expect must never turn into a failure of the real answer.
        usage = getattr(response, "usage", None)
        usage_log["input_tokens"] = getattr(usage, "input_tokens", 0) or 0
        usage_log["output_tokens"] = getattr(usage, "output_tokens", 0) or 0

    stop_reason = getattr(response, "stop_reason", "end_turn")
    if stop_reason not in ("end_turn", "stop_sequence"):
        raise RuntimeError(f"Claude answer ended early (stop_reason={stop_reason!r}) - not showing a partial answer.")

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise RuntimeError("Claude returned an empty answer.")
    return text


async def generate_answer_stream(
    query: str, chunks: list[dict], usage_log: dict | None = None, tenant_id: int = 1
) -> AsyncIterator[str]:
    """
    Yields the answer text in small pieces, gradually - a citation-
    checked Claude answer when NARRATIVE_PROVIDER=claude and
    ANTHROPIC_API_KEY are set, otherwise the deterministic template
    answer - both streamed word-by-word so the console sees it appear
    gradually either way.

    Falls back to the template answer on any Claude error OR on a
    fabricated citation (see _citations_are_grounded()): either way is
    treated as a hiccup that degrades the answer rather than letting a
    broken request or an ungrounded claim reach the client, whose
    (unaffected, already-sent) locked citations stay valid regardless.

    `usage_log`, when passed, records which path was actually taken
    ("grounded", "fabricated_discarded", "claude_error_fallback", or
    "template_only") under its "citation_check_result" key, alongside
    whatever _claude_full_answer() filled in - observability data only,
    never read back to change behavior here.
    """

    settings = get_settings()

    if settings.narrative_provider == "claude" and settings.anthropic_api_key:
        try:
            full_answer = await _claude_full_answer(query, chunks, usage_log=usage_log, tenant_id=tenant_id)
            allowed_filenames = {chunk["filename"] for chunk in chunks}

            if _citations_are_grounded(full_answer, allowed_filenames):
                if usage_log is not None:
                    usage_log["citation_check_result"] = "grounded"
                async for piece in _stream_words(full_answer):
                    yield piece
                return

            if usage_log is not None:
                usage_log["citation_check_result"] = "fabricated_discarded"
            logger.warning(
                "Claude answer cited a source outside the locked set for this "
                "request - discarding it and falling back to the deterministic "
                "template answer instead of letting an ungrounded citation reach the client."
            )
        except Exception:
            if usage_log is not None:
                usage_log["citation_check_result"] = "claude_error_fallback"
            logger.warning(
                "Claude answer generation failed - falling back to the deterministic "
                "template answer.",
                exc_info=True,
            )
    elif usage_log is not None:
        usage_log["citation_check_result"] = "template_only"

    async for piece in _stream_words(_template_answer(chunks)):
        yield piece


RELEVANCE_CHECK_UNAVAILABLE_CODE = "relevance_check_unavailable"
RELEVANCE_CHECK_UNAVAILABLE_TEXT = (
    "The library's sources couldn't be verified right now, so no answer was given. Please try again shortly."
)


async def stream_grounded_answer(
    query: str, results: list[dict], min_chunks: int,
    *, purpose: str = "grounded_answer", matter_id: int | None = None, intake_session_id: int | None = None,
    tenant_id: int = 1,
) -> AsyncIterator[tuple[str, dict]]:
    """
    The one shared implementation of "honest-gap check -> lock sources
    -> generate a grounded answer" - used by
    app/api/end_user_api.py's POST /end-user/query/stream (End User
    scope), app/api/storage_api.py's POST /research/ask (Owner
    library-wide research), and POST /admin/matters/{id}/research
    (Owner Matter-scoped research), so the three scopes can never drift
    into different answer-generation behaviors.

    Takes an ALREADY-RETRIEVED `results` list (the caller runs its own
    scoped retrieval - library-only for Owner research, Matter+library
    for End User and Matter research - so Matter isolation is enforced
    by which retrieval call produced `results`, not by this function).
    `results` is then narrowed to only the chunks
    app/analysis/relevance_guard.py's filter_materially_relevant_chunks()
    verifies materially address the question's actual legal issue
    (never widened, never given anything beyond what `results` already
    contains) BEFORE the honest-gap check below runs, `sources` is
    locked, or generate_answer_stream() ever sees them - this is what
    stops a chunk that merely shares vocabulary with the question
    (from an unrelated CGL/D&O/Workers' Comp/defamation document, say)
    from ever becoming a "supporting" source or reaching the model.
    Yields (event_type, payload)
    tuples: "sources" (once, first), "answer_chunk" (0+, in order),
    "error" (0-1, on a generation failure), "done" (once, always last)
    - the exact same event vocabulary app/api/end_user_api.py already
    formats as Server-Sent Events; a non-streaming caller can instead
    just collect them into one response (see storage_api.py's
    owner_research_ask()).

    Every call also writes one row to the existing llm_usage_log table
    (app/observability/usage_log.py's log_rag_query(), best-effort,
    never raises) recording this exact query, the retrieved chunk
    ids/scores, which model (if any) answered it, token usage, latency,
    and the citation-check outcome - `purpose` distinguishes
    "end_user_query" / "owner_research" / "matter_research" in that log
    without changing the answer/retrieval behavior itself.
    """

    import time

    from app.analysis.relevance_guard import RelevanceCheckUnavailable, filter_materially_relevant_chunks
    from app.observability.usage_log import log_rag_query

    start = time.perf_counter()

    # RELEVANCE GATE: retrieval (app/retrieval/reranker.py's final_score)
    # optimizes for recall and can surface a chunk that merely shares
    # vocabulary with `query` (an insurance policy's exclusions clause
    # mentioning "discrimination", say) without actually addressing the
    # same legal issue. filter_materially_relevant_chunks() only ever
    # REMOVES such chunks - see its docstring - so everything below this
    # line (the honest-gap check, the locked `sources`, and what
    # generate_answer_stream() is even given to work from) already
    # excludes anything not verified as materially relevant. This can
    # never make an ungrounded/fabricated answer more likely; it can
    # only make one that was about to cite something irrelevant refuse
    # to answer instead.
    try:
        relevant_results = filter_materially_relevant_chunks(query, results, tenant_id=tenant_id)
    except RelevanceCheckUnavailable:
        # Still no answer (fail closed) - but NOT the honest-gap text: the
        # library may well cover this, the check just couldn't run. Telling
        # the user "no authority in the library" here would be false.
        yield "sources", {"sources": []}
        yield "error", {"detail": RELEVANCE_CHECK_UNAVAILABLE_TEXT, "code": RELEVANCE_CHECK_UNAVAILABLE_CODE}
        yield "done", {}

        log_rag_query(
            purpose=purpose, query=query, results=results, model="n/a",
            input_tokens=0, output_tokens=0,
            latency_ms=int((time.perf_counter() - start) * 1000),
            citation_check_result=RELEVANCE_CHECK_UNAVAILABLE_CODE,
            matter_id=matter_id, intake_session_id=intake_session_id, tenant_id=tenant_id,
        )
        return

    if len(relevant_results) < min_chunks:
        no_evidence_text = "No authority on this point was found in the firm's legal library."

        yield "sources", {"sources": []}
        yield "answer_chunk", {"text": no_evidence_text}
        yield "done", {}

        log_rag_query(
            purpose=purpose, query=query, results=results, model="n/a",
            input_tokens=0, output_tokens=0,
            latency_ms=int((time.perf_counter() - start) * 1000),
            citation_check_result="insufficient_evidence",
            matter_id=matter_id, intake_session_id=intake_session_id, tenant_id=tenant_id,
        )
        return

    # CITATION LOCK: built once, from this exact `relevant_results` list,
    # and yielded before a single answer token exists. generate_answer_stream()
    # below is only ever given this same, already-fixed, already-relevance-
    # filtered chunk list - an unrelated CGL/D&O/Workers' Comp/defamation
    # document that merely shared keywords with `query` was already
    # excluded above and can never appear as a "supporting" source here.
    sources = [
        {
            "filename": r["filename"],
            "category": r["category"],
            "section": r.get("section"),
            "start_page": r.get("start_page"),
            "end_page": r.get("end_page"),
            "score": r["final_score"],
            "excerpt": r.get("chunk_text"),
        }
        for r in relevant_results
    ]
    yield "sources", {"sources": sources}

    usage_log: dict = {}
    try:
        async for piece in generate_answer_stream(query, relevant_results, usage_log=usage_log, tenant_id=tenant_id):
            yield "answer_chunk", {"text": piece}
    except Exception as exc:
        usage_log.setdefault("citation_check_result", "generation_error")
        yield "error", {"detail": str(exc)}

    yield "done", {}

    log_rag_query(
        purpose=purpose, query=query, results=results,
        model=usage_log.get("model", "template"),
        input_tokens=usage_log.get("input_tokens", 0),
        output_tokens=usage_log.get("output_tokens", 0),
        latency_ms=int((time.perf_counter() - start) * 1000),
        citation_check_result=usage_log.get("citation_check_result", "unknown"),
        matter_id=matter_id, intake_session_id=intake_session_id, tenant_id=tenant_id,
    )

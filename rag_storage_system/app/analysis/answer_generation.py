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
"""
# find (top of file, end of the existing docstring, before the imports):
possible.
"""

import asyncio

# replace with:
possible.

PROMPT-INJECTION RESISTANCE: retrieved chunk text and the caller's
`query` are only ever placed inside clearly delimited data blocks
(KNOWLEDGE BASE EXCERPTS: / QUESTION:), never concatenated into the
system instructions - text embedded in a client's uploaded document or
pasted query can only ever be interpreted as content to answer from,
never as an instruction to the model. Citation lock (see above) is the
backstop even if that boundary were somehow crossed: an ungrounded
citation is caught and discarded regardless of how it was produced.
"""

import asyncio
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


async def _claude_full_answer(query: str, chunks: list[dict]) -> str:
    """
    Runs the real Claude call and returns its full response text -
    buffered, not token-streamed, so generate_answer_stream() can
    citation-check it before any of it reaches the client (see this
    module's docstring for why that rules out live token streaming).
    """

    import anthropic

    from app.api import storage_api
    from app.prompts import get_active_prompt

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    context = "\n\n".join(f"[{_chunk_label(c)}]\n{c['chunk_text']}" for c in chunks)

    system_prompt = get_active_prompt(
        storage_api.metadata_repository, "answer_system_prompt", _DEFAULT_ANSWER_SYSTEM_PROMPT
    )

    response = await client.messages.create(
        model=settings.analysis_model,
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"KNOWLEDGE BASE EXCERPTS:\n{context}\n\nQUESTION:\n{query}"}
        ],
    )

    return "".join(block.text for block in response.content if block.type == "text")


async def generate_answer_stream(query: str, chunks: list[dict]) -> AsyncIterator[str]:
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
    """

    settings = get_settings()

    if settings.narrative_provider == "claude" and settings.anthropic_api_key:
        try:
            full_answer = await _claude_full_answer(query, chunks)
            allowed_filenames = {chunk["filename"] for chunk in chunks}

            if _citations_are_grounded(full_answer, allowed_filenames):
                async for piece in _stream_words(full_answer):
                    yield piece
                return

            logger.warning(
                "Claude answer cited a source outside the locked set for this "
                "request - discarding it and falling back to the deterministic "
                "template answer instead of letting an ungrounded citation reach the client."
            )
        except Exception:
            logger.warning(
                "Claude answer generation failed - falling back to the deterministic "
                "template answer.",
                exc_info=True,
            )

    async for piece in _stream_words(_template_answer(chunks)):
        yield piece

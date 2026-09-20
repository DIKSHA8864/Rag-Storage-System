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
"""

import asyncio
from typing import AsyncIterator

from config.settings import get_settings

_WORDS_PER_CHUNK = 6
_STREAM_DELAY_SECONDS = 0.03


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


async def _claude_answer_stream(query: str, chunks: list[dict]) -> AsyncIterator[str]:
    import anthropic

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    context = "\n\n".join(f"[{_chunk_label(c)}]\n{c['chunk_text']}" for c in chunks)

    system_prompt = (
        "Answer the user's question using ONLY the knowledge-base excerpts below. "
        "Never introduce outside knowledge or invented facts. If the excerpts don't "
        "fully answer the question, say what is and isn't supported. Keep the answer concise."
    )

    async with client.messages.stream(
        model=settings.analysis_model,
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"KNOWLEDGE BASE EXCERPTS:\n{context}\n\nQUESTION:\n{query}"}
        ],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def generate_answer_stream(query: str, chunks: list[dict]) -> AsyncIterator[str]:
    """
    Yields the answer text in small pieces, gradually - real
    Claude token streaming when NARRATIVE_PROVIDER=claude and
    ANTHROPIC_API_KEY are set, otherwise the deterministic template
    answer streamed word-by-word so the console still sees it appear
    gradually either way.

    Falls back to the template stream on any Claude error - a hiccup
    degrades the answer, it never breaks a request whose (unaffected,
    already-sent) locked citations were already delivered to the client.
    """

    settings = get_settings()

    if settings.narrative_provider == "claude" and settings.anthropic_api_key:
        try:
            async for piece in _claude_answer_stream(query, chunks):
                yield piece
            return
        except Exception:
            pass

    async for piece in _stream_words(_template_answer(chunks)):
        yield piece
"""
One Claude call that must return JSON matching a schema - the pattern the
Work Plan sets for anything that becomes a document ("the LLM is prompted
to return structured JSON matching the docgen schema - the model never
formats documents itself; formatting lives in templates").

Raises ClaudeUnavailable (never returns partial or guessed content) when
there's no API key, the call fails, it stops early, or the JSON doesn't
parse - callers fall back to their template output and say so.
"""

import json
import logging
from typing import Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class ClaudeUnavailable(Exception):
    """No usable model output - the caller must not pretend it has one."""


def call_claude_json(
    purpose: str, model: str, system: str, user_content: str, schema: dict, tenant_id: int = 1,
    max_tokens: int = 16000, effort: str = "medium", intake_session_id: Optional[int] = None,
    matter_id: Optional[int] = None,
) -> dict:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ClaudeUnavailable("ANTHROPIC_API_KEY is not set.")

    import anthropic

    from app.observability.usage_log import track_llm_call

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        with track_llm_call(purpose, model, matter_id=matter_id, intake_session_id=intake_session_id,
                            tenant_id=tenant_id) as record_usage:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
            usage = getattr(response, "usage", None)
            record_usage(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
    except Exception as exc:
        logger.warning("%s: Claude call failed.", purpose, exc_info=True)
        raise ClaudeUnavailable(f"The Claude call failed: {exc}") from exc

    stop_reason = getattr(response, "stop_reason", "end_turn")
    if stop_reason not in ("end_turn", "stop_sequence"):
        raise ClaudeUnavailable(f"Claude stopped early ({stop_reason}).")
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClaudeUnavailable("Claude returned unreadable JSON.") from exc
    if not isinstance(parsed, dict):
        raise ClaudeUnavailable("Claude returned JSON of the wrong shape.")
    return parsed


def numbered_passages(chunks: list[dict], max_chars: int = 1500) -> tuple[str, dict[str, dict]]:
    """Library/matter passages as clearly delimited, id-tagged blocks - and the id -> chunk map to check citations against."""

    by_id: dict[str, dict] = {}
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        source_id = f"S{index}"
        by_id[source_id] = chunk
        where = chunk.get("filename", "unknown")
        if chunk.get("section"):
            where += f" - section {chunk['section']}"
        origin = "case record" if str(chunk.get("category", "")).startswith("matter-") else "library"
        blocks.append(f'<passage id="{source_id}" source="{where}" origin="{origin}">\n'
                      f"{chunk.get('chunk_text', '')[:max_chars]}\n</passage>")
    return "\n\n".join(blocks), by_id

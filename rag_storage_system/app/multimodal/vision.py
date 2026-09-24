"""
Vision provider interface - describes the visual content of an image
that OCR alone doesn't capture (a photo of a scene, a diagram) as a
short caption. Pluggable, same pattern as app/multimodal/ocr.py.
"mock" (default) needs no external service; "claude" (see
ClaudeVisionProvider below) is a real implementation using Claude's
vision input, gated by ANTHROPIC_API_KEY exactly like
app/analysis/claude_narrative.py's ClaudeNarrativeGenerator.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from config.settings import get_settings

_EXTENSION_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
}

_CAPTION_SYSTEM_PROMPT = (
    "You are describing an image attached to a legal intake record. "
    "In 1-3 factual sentences, describe only what is visibly present in "
    "the image - people's actions, objects, visible damage, text, "
    "setting. Never guess at identities, causes, fault, dates, or "
    "anything not directly visible. If the image is unclear or shows "
    "nothing of substance, say so plainly instead of speculating."
)


class VisionProvider(ABC):
    """Abstract base class for all vision/captioning providers."""

    name: str

    @abstractmethod
    def describe(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        """Returns (caption, is_mock) - see OCRProvider.extract_text()'s docstring for what is_mock guards."""

        raise NotImplementedError


class MockVisionProvider(VisionProvider):
    """Free, offline default - see MockOCRProvider's docstring for the same rationale."""

    name = "mock"

    def describe(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        return (
            f"[MOCK CAPTION] No vision engine is configured. "
            f"'{filename}' ({len(image_bytes)} bytes) was received but "
            "not described - attorney review required.",
            True,
        )


class ClaudeVisionProvider(VisionProvider):
    """
    Real image captioning via Claude's vision input. Same
    hallucination-conscious framing as app/analysis/claude_narrative.py:
    Claude is only ever asked to describe what is literally visible,
    never to infer fault/cause/identity - this is intake evidence, not
    a scene it should interpret. Logs its usage to the same
    llm_usage_log table as every other Claude call
    (app/observability/usage_log.py's track_llm_call()) under
    purpose="vision_captioning" - KNOWN GAP: VisionProvider.describe()
    takes no tenant_id, so this is logged under the default tenant (1)
    regardless of which tenant's Client intake triggered it. Threading
    tenant_id through app/multimodal/pipeline.py -> image_processor.py
    -> describe() (the same mechanical change Phase 5 Step 24 made
    elsewhere) would be needed before Step 25's billing
    max_llm_calls_per_month check can see intake-driven Vision usage.
    """

    name = "claude"

    def __init__(self):
        settings = get_settings()

        if not settings.anthropic_api_key:
            raise RuntimeError(
                "VISION_PROVIDER=claude requires ANTHROPIC_API_KEY to be set."
            )

        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.analysis_model

    def describe(self, image_bytes: bytes, filename: str) -> tuple[str, bool]:
        import base64

        media_type = _EXTENSION_MEDIA_TYPES.get(Path(filename).suffix.lower())
        if media_type is None:
            raise RuntimeError(
                f"ClaudeVisionProvider cannot caption '{filename}': unsupported image "
                "format for Claude's vision input (supported: png/jpg/jpeg/bmp)."
            )

        from app.observability.usage_log import track_llm_call

        with track_llm_call("vision_captioning", self._model) as record_usage:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=300,
                system=_CAPTION_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64.b64encode(image_bytes).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": f"Describe the image '{filename}'."},
                        ],
                    }
                ],
            )
            record_usage(response.usage.input_tokens, response.usage.output_tokens)

        caption = "".join(block.text for block in response.content if block.type == "text")
        return caption.strip(), False


def get_vision_provider() -> VisionProvider:
    provider = get_settings().vision_provider

    if provider == "mock":
        return MockVisionProvider()
    if provider == "claude":
        return ClaudeVisionProvider()

    raise RuntimeError(f"Unknown VISION_PROVIDER: {provider!r}")

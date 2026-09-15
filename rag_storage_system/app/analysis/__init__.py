"""
Narrative generator factory - the single place that decides which
NarrativeGenerator implementation app/analysis/report_builder.py talks
to, mirroring app/embeddings/__init__.py's get_embedding_provider().

Controlled by NARRATIVE_PROVIDER (config/settings.py / .env):
    "template" (default) -> TemplateNarrativeGenerator, free,
        deterministic, no API key needed.
    "claude"             -> ClaudeNarrativeGenerator, needs
        ANTHROPIC_API_KEY.
"""

from app.analysis.base import NarrativeGenerator

_generator_instance: NarrativeGenerator | None = None


def get_narrative_generator() -> NarrativeGenerator:
    global _generator_instance

    if _generator_instance is None:
        from config.settings import get_settings

        settings = get_settings()

        if settings.narrative_provider == "claude" and settings.anthropic_api_key:
            from app.analysis.claude_narrative import ClaudeNarrativeGenerator

            _generator_instance = ClaudeNarrativeGenerator()
        else:
            from app.analysis.template_narrative import TemplateNarrativeGenerator

            _generator_instance = TemplateNarrativeGenerator()

    return _generator_instance

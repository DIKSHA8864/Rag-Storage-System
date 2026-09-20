"""
DB-backed prompt versioning (app/metadata/base.py's
get_active_prompt()/create_prompt_version()) - lets the Owner change
and roll back the system prompts driving Claude-backed generation
(app/analysis/claude_narrative.py, app/analysis/answer_generator.py)
without a code change or restart. Every version ever saved is kept;
only one per `name` is ever active at a time.
"""

from app.metadata.base import MetadataRepository


def get_active_prompt(metadata_repository: MetadataRepository, name: str, default_text: str) -> str:
    active = metadata_repository.get_active_prompt_version(name)
    return active["text"] if active else default_text
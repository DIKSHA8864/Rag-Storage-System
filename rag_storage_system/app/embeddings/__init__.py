"""
Embedding provider factory - the single place that decides which
EmbeddingProvider implementation the rest of the app talks to,
mirroring app/storage/__init__.py's get_storage_backend() and
app/metadata/__init__.py's get_metadata_repository().

Controlled by EMBEDDING_PROVIDER (config/settings.py / .env):
    "sentence_transformers" (default) -> SentenceTransformerEmbeddingProvider,
        a free local model, no API key needed.

Add a hosted option (OpenAI, Cohere, ...) later by adding a branch
here and a new provider class - see app/embeddings/base.py.
"""

from app.embeddings.base import EmbeddingProvider

# Keyed by model name, not just one singleton: get_embedding_provider()
# can be asked for a specific model (embedding_manager.embed_texts's
# optional model_name override), and each one loads its own model.
_provider_instances: dict[str, EmbeddingProvider] = {}


def get_embedding_provider(model_name: str | None = None) -> EmbeddingProvider:
    from config.settings import get_settings

    settings = get_settings()
    model_name = model_name or settings.embedding_model

    if model_name not in _provider_instances:
        if settings.embedding_provider == "sentence_transformers":
            from app.embeddings.sentence_transformer_provider import (
                SentenceTransformerEmbeddingProvider,
            )

            _provider_instances[model_name] = SentenceTransformerEmbeddingProvider(model_name)
        else:
            raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.embedding_provider}")

    return _provider_instances[model_name]

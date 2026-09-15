"""
Embedding provider interface.

Same abstraction principle as app/storage/base.py and
app/metadata/base.py: everything that turns text into vectors goes
through an object that implements EmbeddingProvider, instead of
app/embeddings/embedding_manager.py calling a specific SDK (sentence-
transformers, an OpenAI/Cohere/etc HTTP API, ...) directly. Swapping
the provider later - e.g. a hosted API instead of a local model - is a
factory change in app/embeddings/__init__.py (get_embedding_provider),
not a rewrite of embedding_manager.py or anything upstream of it.

To add a new provider later:
    1. Create app/embeddings/<name>_provider.py with a class that
       subclasses EmbeddingProvider and fills in every abstract
       member below.
    2. Change get_embedding_provider() in app/embeddings/__init__.py
       to construct it (gated on EMBEDDING_PROVIDER / config/settings.py).
No caller (embedding_manager.py, the processing job, retrieval) should
need to change.
"""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base class for all embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts in one call.

        Always prefer passing every text you need embedded in one
        call over calling this once per text - batching is far
        faster for most providers (one model forward pass locally,
        one HTTP round trip for a hosted API) than paying per-call
        overhead for each short chunk-sized text individually.

        Returns one vector per input text, same order, each of
        length `dimension`. Returns [] for an empty input list.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier for the specific model in use, e.g. 'all-MiniLM-L6-v2'."""
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Length of every vector this provider returns."""
        raise NotImplementedError

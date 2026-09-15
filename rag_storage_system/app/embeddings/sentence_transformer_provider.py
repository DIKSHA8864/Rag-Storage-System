"""
Local, free embedding provider backed by sentence-transformers - the
provider get_embedding_provider() (app/embeddings/__init__.py) returns
by default. Needs no API key and no network access beyond the
one-time model download, which is why it's the default rather than a
hosted API: free to run, nothing to configure for a first pass.

See app/embeddings/base.py for the interface this implements, and its
module docstring for how to add a hosted provider alongside this one
later.
"""

from sentence_transformers import SentenceTransformer

from app.embeddings.base import EmbeddingProvider


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):

    def __init__(self, model_name: str):
        self._model_name = model_name
        # Loading a SentenceTransformer model is expensive (disk/network
        # I/O plus moving weights onto a device) - one instance per
        # provider object, and get_embedding_provider() caches provider
        # instances by model name so this only happens once per model
        # per process.
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [vector.tolist() for vector in vectors]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()

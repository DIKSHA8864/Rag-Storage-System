"""
PHASE 6 - EMBEDDINGS

Turns Phase 5 output (Chunks in storage/chunks/) into embedding
vectors, one per chunk, using the model configured as EMBEDDING_MODEL
(config/settings.py / .env - defaults to all-MiniLM-L6-v2, a
384-dimension sentence-transformers model chunker.py already sizes
chunks for).

Each chunk's vector is written next to a copy of its source chunk
data under storage/embeddings/<document_id>/<chunk_id>.json,
mirroring the same per-document folder convention every earlier
phase uses.

This phase does not talk to a vector database - that is
app/vector_store's job (app/vector_store/vector_repository.py, backed
by pgvector - see app/jobs/processing.py for how the two connect).
Keeping embedding generation and vector-store indexing separate means
either one can be swapped (a different provider here, a different
vector store there) without touching the other.

Embedding generation itself goes through the EmbeddingProvider
interface (app/embeddings/base.py), not a specific SDK - see
app/embeddings/__init__.py's get_embedding_provider() for which
provider is active (EMBEDDING_PROVIDER / config/settings.py).
"""

import json
from typing import Optional

from app.embeddings import get_embedding_provider
from config.settings import get_settings

_settings = get_settings()

CHUNKS_DIR = _settings.resolve(_settings.chunks_storage_path)
EMBEDDINGS_DIR = _settings.resolve(_settings.embeddings_storage_path)


def embed_texts(texts: list[str], model_name: Optional[str] = None) -> list[list[float]]:
    """
    Embed a batch of texts in one pass.

    Always prefer this over calling embed_chunk() in a loop when
    embedding more than one chunk - encoding a batch is far faster
    than one call per text, since the model's fixed per-call overhead
    would otherwise dominate for short chunk-sized texts.
    """

    if not texts:
        return []

    provider = get_embedding_provider(model_name)

    return provider.embed(texts)


def embedding_input(chunk: dict) -> str:
    """
    The text actually embedded for a library chunk: a context header -
    filename | folder | section, then the file's one-line summary - above
    the chunk text (Blueprint Work Plan M1: "prepend to every chunk:
    filename, folder/category path, section heading, and the file's
    one-line summary header"). A passage that doesn't repeat its topic
    ("the court may appoint a special master") still lands near questions
    about that topic. The stored/cited chunk_text stays the passage alone.
    """

    metadata = chunk.get("metadata") or {}
    header = " | ".join(part for part in (chunk.get("filename"), metadata.get("category"), chunk.get("section")) if part)
    return "\n".join(part for part in (header, metadata.get("summary"), chunk["text"]) if part)


def _attach_embedding(chunk: dict, embedding: list[float], model_name: str) -> dict:
    return {
        "chunk_id": chunk["chunk_id"],
        "segment_id": chunk["segment_id"],
        "document_id": chunk["document_id"],
        "filename": chunk["filename"],
        "chunk_index": chunk["chunk_index"],
        "start_page": chunk["start_page"],
        "end_page": chunk["end_page"],
        "page_count": chunk.get("page_count"),
        "chapter": chunk.get("chapter"),
        "section": chunk.get("section"),
        "subsection": chunk.get("subsection"),
        "text": chunk["text"],
        "word_count": chunk.get("word_count"),
        "metadata": chunk.get("metadata", {}),
        "embedding_model": model_name,
        "embedding_dim": len(embedding),
        "embedding": embedding,
    }


def embed_chunk(chunk: dict, model_name: Optional[str] = None) -> dict:
    """
    Embed one chunk (as loaded from a Phase 5 chunk JSON file).

    For more than one chunk, call embed_texts() on all their texts
    together instead - see its docstring.
    """

    model_name = model_name or get_settings().embedding_model
    embedding = embed_texts([chunk["text"]], model_name=model_name)[0]

    return _attach_embedding(chunk, embedding, model_name)


def process_all_chunks() -> list[dict]:
    """
    Embed every chunk currently in storage/chunks/, writing one
    output JSON per chunk under storage/embeddings/. Safe to call
    again after new chunks are produced - always reprocesses
    everything currently in storage/chunks/.
    """

    if not CHUNKS_DIR.exists():
        return []

    chunk_paths = sorted(CHUNKS_DIR.rglob("*.json"))

    if not chunk_paths:
        return []

    chunks = []
    for chunk_path in chunk_paths:
        with open(chunk_path, "r", encoding="utf-8") as file:
            chunks.append(json.load(file))

    model_name = get_settings().embedding_model
    embeddings = embed_texts([embedding_input(chunk) for chunk in chunks], model_name=model_name)

    results = []

    for chunk, embedding in zip(chunks, embeddings):
        data = _attach_embedding(chunk, embedding, model_name)

        output_dir = EMBEDDINGS_DIR / chunk["document_id"]
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / f"{chunk['chunk_id']}.json"

        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

        results.append(data)

    return results

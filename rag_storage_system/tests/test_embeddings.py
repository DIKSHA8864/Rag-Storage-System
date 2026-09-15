"""
Embedding tests (Phase 6): turning Phase 5 chunks into vectors with
the configured sentence-transformers model.

These load the real model (all-MiniLM-L6-v2, ~90MB, cached after the
first run) rather than mocking it - a mocked encoder couldn't catch a
real regression like the wrong model name or a broken dimension, and
the model loads in well under a second once cached.
"""

import json

import pytest

from app.embeddings import embedding_manager
from app.embeddings.embedding_manager import embed_chunk, embed_texts, process_all_chunks


def _chunk(chunk_id="c-0001", document_id="policy", text="Some chunk content."):
    return {
        "chunk_id": chunk_id,
        "segment_id": "policy-segment-0001",
        "document_id": document_id,
        "filename": "policy.txt",
        "chunk_index": 1,
        "start_page": 1,
        "end_page": 1,
        "page_count": 1,
        "chapter": None,
        "section": "1.1. Background",
        "subsection": None,
        "text": text,
        "word_count": len(text.split()),
        "metadata": {"file_type": "txt"},
    }


# ---------------------------------------------------------------------
# embed_texts()
# ---------------------------------------------------------------------


def test_embed_texts_returns_one_vector_per_text():
    vectors = embed_texts(["first chunk", "second chunk", "third chunk"])
    assert len(vectors) == 3


def test_embed_texts_matches_model_dimension():
    vectors = embed_texts(["hello world"])
    assert len(vectors[0]) == 384  # all-MiniLM-L6-v2's output size


def test_embed_texts_empty_list_returns_empty():
    assert embed_texts([]) == []


def test_embed_texts_similar_text_is_more_similar_than_unrelated():
    a, b, c = embed_texts(
        [
            "The quick brown fox jumps over the lazy dog.",
            "A fast fox leaps above a sleepy dog.",
            "Quarterly revenue increased due to strong sales.",
        ]
    )

    def cosine(u, v):
        dot = sum(x * y for x, y in zip(u, v))
        norm_u = sum(x * x for x in u) ** 0.5
        norm_v = sum(y * y for y in v) ** 0.5
        return dot / (norm_u * norm_v)

    similar_score = cosine(a, b)
    unrelated_score = cosine(a, c)

    assert similar_score > unrelated_score


# ---------------------------------------------------------------------
# embed_chunk()
# ---------------------------------------------------------------------


def test_embed_chunk_attaches_vector_and_preserves_metadata():
    result = embed_chunk(_chunk())

    assert result["chunk_id"] == "c-0001"
    assert result["section"] == "1.1. Background"
    assert result["embedding_model"] == "all-MiniLM-L6-v2"
    assert result["embedding_dim"] == len(result["embedding"]) == 384


# ---------------------------------------------------------------------
# process_all_chunks() - mirrors storage/chunks -> storage/embeddings
# ---------------------------------------------------------------------


def test_process_all_chunks_writes_one_file_per_chunk(tmp_path, monkeypatch):
    chunks_dir = tmp_path / "chunks"
    embeddings_dir = tmp_path / "embeddings"

    monkeypatch.setattr(embedding_manager, "CHUNKS_DIR", chunks_dir)
    monkeypatch.setattr(embedding_manager, "EMBEDDINGS_DIR", embeddings_dir)

    document_dir = chunks_dir / "policy"
    document_dir.mkdir(parents=True)

    for i in range(2):
        chunk = _chunk(chunk_id=f"c-000{i}", text=f"Chunk number {i} content.")
        (document_dir / f"c-000{i}.json").write_text(
            json.dumps(chunk), encoding="utf-8"
        )

    results = process_all_chunks()

    assert len(results) == 2
    assert all(r["embedding_dim"] == 384 for r in results)

    output_files = sorted((embeddings_dir / "policy").glob("*.json"))
    assert len(output_files) == 2

    with open(output_files[0], encoding="utf-8") as f:
        saved = json.load(f)
    assert "embedding" in saved
    assert len(saved["embedding"]) == 384


def test_process_all_chunks_empty_when_no_chunks_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_manager, "CHUNKS_DIR", tmp_path / "does_not_exist")
    assert process_all_chunks() == []


def test_process_all_chunks_empty_when_no_chunk_files(tmp_path, monkeypatch):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()

    monkeypatch.setattr(embedding_manager, "CHUNKS_DIR", chunks_dir)
    assert process_all_chunks() == []

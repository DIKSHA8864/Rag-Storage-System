"""
Tests for app/analysis/ingestion.py - turning an End User's raw
submission (pasted text or a file) into embedded chunks via the exact
same extraction/segmentation/chunking/embedding functions Owner
uploads use. Loads the real embedding model (not mocked), same as
tests/test_embeddings.py - it's small and cached after the first run.

Confirms nothing is written to disk (storage/processed, storage/
segments, storage/chunks - the whole point of these being ephemeral).
"""

from app.analysis import ingestion


def test_is_supported_submission_matches_allowed_extensions():
    assert ingestion.is_supported_submission("policy.pdf") is True
    assert ingestion.is_supported_submission("policy.docx") is True
    assert ingestion.is_supported_submission("policy.txt") is True
    assert ingestion.is_supported_submission("policy.doc") is False
    assert ingestion.is_supported_submission("recording.mp3") is False


def test_process_text_submission_returns_embedded_chunks():
    chunks = ingestion.process_text_submission(
        "Vendor contracts must be reviewed on an annual basis by the compliance team."
    )

    assert len(chunks) >= 1
    assert all("embedding" in chunk and len(chunk["embedding"]) == 384 for chunk in chunks)
    assert all(isinstance(chunk["text"], str) and chunk["text"] for chunk in chunks)


def test_process_submission_with_txt_file_bytes():
    data = b"The remote work policy allows employees to work from home two days per week."
    chunks = ingestion.process_submission("remote_policy.txt", data)

    assert len(chunks) == 1
    assert "remote work policy" in chunks[0]["text"].lower()


def test_process_submission_does_not_write_to_shared_storage(tmp_path, monkeypatch):
    from app.extraction import extractor_manager
    from app.segmentation import chunker, segmentation_manager

    # Point every phase's storage dir at throwaway locations that stay
    # empty for the whole test - process_submission() must never touch
    # them, since an End User's submission isn't part of the knowledge
    # base.
    monkeypatch.setattr(extractor_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(segmentation_manager, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "SEGMENTS_DIR", tmp_path / "segments")
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")

    ingestion.process_text_submission("A short submission to check for stray writes.")

    assert not (tmp_path / "processed").exists()
    assert not (tmp_path / "segments").exists()
    assert not (tmp_path / "chunks").exists()

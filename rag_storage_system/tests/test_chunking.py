"""
Chunking tests (Phase 5), porting the manual checks
scripts/test_chunking.py used to only print, into real assertions.
"""

from app.segmentation.chunker import chunk_segment, split_into_sentences


# ---------------------------------------------------------------------
# split_into_sentences()
# ---------------------------------------------------------------------


def test_split_into_sentences_basic():
    sentences = split_into_sentences("First sentence. Second sentence. Third one!")
    assert sentences == ["First sentence.", "Second sentence.", "Third one!"]


def test_split_into_sentences_does_not_break_on_abbreviations():
    sentences = split_into_sentences("Dr. Smith met Mrs. Jones at the office.")
    assert len(sentences) == 1


def test_split_into_sentences_empty_text():
    assert split_into_sentences("   ") == []


# ---------------------------------------------------------------------
# chunk_segment()
# ---------------------------------------------------------------------


def _segment(text, start_page=1, end_page=1):
    return {
        "segment_id": "policy-segment-0001",
        "document_id": "policy",
        "filename": "policy.txt",
        "start_page": start_page,
        "end_page": end_page,
        "chapter": None,
        "section": "1.1. Background",
        "subsection": None,
        "text": text,
        "metadata": {"file_type": "txt"},
    }


def test_chunk_segment_keeps_short_segment_as_one_chunk():
    chunks = chunk_segment(_segment("A short segment. Just two sentences."))

    assert len(chunks) == 1
    assert chunks[0].split_reason == "whole_segment"
    assert chunks[0].chunk_id == "policy-segment-0001-chunk-0001"


def test_chunk_segment_splits_long_segment_by_word_budget():
    long_text = " ".join(f"Sentence number {i} has several words in it." for i in range(60))

    chunks = chunk_segment(_segment(long_text))

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.word_count <= 180 or chunk.split_reason == "hard_split_long_sentence"


def test_chunk_segment_carries_overlap_between_adjacent_chunks():
    long_text = " ".join(f"Sentence number {i} has several words in it." for i in range(60))

    chunks = chunk_segment(_segment(long_text))

    assert len(chunks) >= 2
    # The overlap tail of chunk 1 should reappear at the start of chunk 2.
    first_chunk_tail = chunks[0].text.split(".")[-2].strip()
    assert first_chunk_tail in chunks[1].text


def test_chunk_segment_empty_text_returns_no_chunks():
    assert chunk_segment(_segment("")) == []


def test_chunk_segment_preserves_page_range():
    chunks = chunk_segment(_segment("Some content here.", start_page=3, end_page=3))
    assert chunks[0].start_page == 3
    assert chunks[0].end_page == 3

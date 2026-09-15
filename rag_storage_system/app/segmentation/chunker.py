"""
PHASE 5 - CHUNKING

Turns Phase 4 output (LogicalSegments in storage/segments/) into
smaller, embedding-ready Chunks, and writes them to storage/chunks/.

Why this phase exists:
    A LogicalSegment can legally span dozens of pages, because
    documents have no page limit and a segment only ends at a real
    chapter/section boundary. Embedding an 11,000-word segment as one
    vector would produce a diluted, low-quality embedding, so each
    segment is split into smaller chunks sized for the embedding
    model (EMBEDDING_MODEL=all-MiniLM-L6-v2, ~256 token limit).

Rules:
    - A chunk never ends mid-sentence or mid-word.
    - A segment that already fits in one chunk is kept as a single
      chunk (no pointless fragmentation).
    - Adjacent chunks share a small sentence overlap so retrieval
      does not lose context that fell on a chunk boundary.
    - Every chunk keeps the exact page range it came from, so
      source/page traceability survives splitting.

This file does not modify Phase 4 (app/segmentation/logical_segmenter.py
and app/segmentation/segmentation_manager.py) or its output format. It
only reads the segment JSON that phase already produces, plus the
original per-page text from storage/processed/<document_id>/extracted.json
so that page attribution stays accurate after a segment is split.
"""

import json
import re
from pathlib import Path

from app.segmentation.models import Chunk
from app.segmentation.structure_detector import detect_structure
from config.settings import get_settings

_settings = get_settings()

PROCESSED_DIR = _settings.resolve(_settings.processed_storage_path)
SEGMENTS_DIR = _settings.resolve(_settings.segments_storage_path)
CHUNKS_DIR = _settings.resolve(_settings.chunks_storage_path)


# ---------------------------------------------------------------------
# Sizing.
#
# all-MiniLM-L6-v2 truncates at 256 tokens. English text is roughly
# ~1.3 tokens per word, so 180 words (~234 tokens) leaves a safety
# margin instead of chunking right up against the model's limit.
# ---------------------------------------------------------------------

MAX_CHUNK_WORDS = 180
OVERLAP_WORDS = 30

WORDS_TO_TOKENS_FACTOR = 1.3


# ---------------------------------------------------------------------
# Sentence splitting.
#
# The PDF/DOCX extractors do not preserve paragraph breaks (PyMuPDF's
# "text" mode inserts a plain "\n" after every wrapped line, not just
# real paragraphs), so sentences - not paragraphs - are the smallest
# safe splitting unit available.
# ---------------------------------------------------------------------

_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(\[])')

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc",
    "e.g", "i.e", "no", "vol", "p", "pp", "fig", "eq", "al", "cf",
    "u.s", "n.a", "inc", "co", "corp", "ltd", "rev", "sec", "art",
    "para", "ch", "fed", "r", "civ", "const", "amend",
}


def split_into_sentences(text: str) -> list[str]:
    """
    Split normal prose into sentences without breaking on common
    abbreviations. Not perfect (no sentence splitter on plain
    English text ever is), but it keeps chunk boundaries sane.
    """

    normalized = re.sub(r"\s+", " ", text).strip()

    if not normalized:
        return []

    raw_parts = _SENTENCE_BOUNDARY.split(normalized)

    sentences: list[str] = []
    buffer = ""

    for index, part in enumerate(raw_parts):

        buffer = f"{buffer} {part}".strip() if buffer else part

        words = buffer.split()
        last_word = words[-1].strip(".!?").lower() if words else ""

        is_last_part = index == len(raw_parts) - 1

        if last_word in _ABBREVIATIONS and not is_last_part:
            # Likely an abbreviation, not a real sentence end.
            # Keep accumulating into the same buffer.
            continue

        sentences.append(buffer)
        buffer = ""

    if buffer:
        sentences.append(buffer)

    return sentences


def _hard_split_words(words: list[str], max_words: int) -> list[list[str]]:
    return [
        words[i:i + max_words]
        for i in range(0, len(words), max_words)
    ]


# ---------------------------------------------------------------------
# Page reconstruction.
#
# LogicalSegment.text is the merged text of several pages with no
# markers left behind, so to keep chunk-level page traceability we
# re-derive, from the original extracted.json, exactly which pages
# feed a segment - mirroring the inclusion rules
# logical_segmenter.segment_document() already applies (skip empty
# pages, skip a page-1 title page).
# ---------------------------------------------------------------------

def _is_title_page(page_number: int, text: str) -> bool:

    if page_number != 1 or not text:
        return False

    structures = detect_structure(text, page_number)

    has_chapter = any(
        item.element_type == "chapter" for item in structures
    )

    has_section = any(
        item.element_type == "section" for item in structures
    )

    return has_chapter and has_section


def _load_document_pages(document_id: str) -> list[dict] | None:

    extracted_path = PROCESSED_DIR / document_id / "extracted.json"

    if not extracted_path.exists():
        return None

    try:
        with open(extracted_path, "r", encoding="utf-8") as file:
            document = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    return document.get("pages", [])


def _resolve_included_pages(segment: dict) -> list[tuple[int, str]]:
    """
    Return an ordered [(page_number, page_text), ...] list covering
    the segment's page range.

    Falls back to treating the whole segment as one page-range block
    when the original extracted.json can no longer be found, so
    chunking still works - just with coarser page attribution.
    """

    start_page = segment["start_page"]
    end_page = segment["end_page"]

    document_pages = _load_document_pages(segment["document_id"])

    if not document_pages:
        return [(start_page, segment["text"])]

    included = []

    for page in document_pages:

        page_number = page.get("page_number")

        if page_number is None:
            continue

        if page_number < start_page or page_number > end_page:
            continue

        text = page.get("text", "").strip()

        if not text:
            continue

        if _is_title_page(page_number, text):
            continue

        included.append((page_number, text))

    if not included:
        return [(start_page, segment["text"])]

    return included


# ---------------------------------------------------------------------
# Packing sentences into word-budgeted chunks.
# ---------------------------------------------------------------------

def _page_sentences(
    included_pages: list[tuple[int, str]],
) -> list[tuple[int, str]]:

    items = []

    for page_number, page_text in included_pages:

        for sentence in split_into_sentences(page_text):
            items.append((page_number, sentence))

    return items


def _pack_sentences(
    sentence_items: list[tuple[int, str]],
    max_words: int,
    overlap_words: int,
) -> list[list[tuple[int, str]]]:

    chunks: list[list[tuple[int, str]]] = []

    current: list[tuple[int, str]] = []
    current_words = 0

    def close_chunk() -> list[tuple[int, str]]:
        nonlocal current, current_words

        if not current:
            return []

        chunks.append(list(current))

        # Carry the tail of this chunk into the next one so
        # adjacent chunks overlap instead of hard-cutting context.
        carry: list[tuple[int, str]] = []
        carry_words = 0

        for page_number, sentence in reversed(current):

            sentence_words = len(sentence.split())

            # A sentence bigger than the overlap budget on its own
            # is never carried - better to have no overlap at this
            # boundary than to blow past overlap_words.
            if sentence_words > overlap_words:
                break

            if carry_words + sentence_words > overlap_words:
                break

            carry.insert(0, (page_number, sentence))
            carry_words += sentence_words

        current = carry
        current_words = carry_words

        return chunks[-1]

    for page_number, sentence in sentence_items:

        sentence_words = len(sentence.split())

        if sentence_words > max_words:
            # A single "sentence" longer than the whole chunk budget
            # (malformed text, OCR noise, a giant citation run-on).
            # Treat it as a hard boundary: flush what we have, split
            # the oversized sentence on word boundaries, and don't
            # carry overlap across it.
            close_chunk()
            current = []
            current_words = 0

            words = sentence.split()

            for piece_words in _hard_split_words(words, max_words):
                chunks.append([(page_number, " ".join(piece_words))])

            continue

        if current_words + sentence_words > max_words and current:
            close_chunk()

            # Even a freshly-carried-over overlap plus this one
            # sentence can, in rare cases, still not fit (e.g. a
            # near-max-words overlap tail followed by another large
            # sentence). Drop the overlap rather than exceed the
            # word budget.
            if current_words + sentence_words > max_words:
                current = []
                current_words = 0

        current.append((page_number, sentence))
        current_words += sentence_words

    close_chunk()

    return chunks


def _split_reason(chunk_count: int, item_count: int, word_count: int) -> str:

    if chunk_count == 1:
        return "whole_segment"

    if item_count == 1 and word_count > MAX_CHUNK_WORDS:
        return "hard_split_long_sentence"

    return "sentence_pack"


# ---------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------

def chunk_segment(segment: dict) -> list[Chunk]:
    """
    Split one Phase 4 segment (as loaded from its JSON file) into
    embedding-ready Chunks.
    """

    included_pages = _resolve_included_pages(segment)
    sentence_items = _page_sentences(included_pages)

    if not sentence_items:
        return []

    packed = _pack_sentences(
        sentence_items,
        max_words=MAX_CHUNK_WORDS,
        overlap_words=OVERLAP_WORDS,
    )

    chunk_count = len(packed)
    chunks = []

    for index, items in enumerate(packed, start=1):

        text = " ".join(sentence for _, sentence in items)
        word_count = len(text.split())

        page_numbers = [page_number for page_number, _ in items]

        chunk = Chunk(
            chunk_id=f"{segment['segment_id']}-chunk-{index:04d}",
            segment_id=segment["segment_id"],
            document_id=segment["document_id"],
            filename=segment["filename"],
            chunk_index=index,
            start_page=min(page_numbers),
            end_page=max(page_numbers),
            chapter=segment.get("chapter"),
            section=segment.get("section"),
            subsection=segment.get("subsection"),
            text=text,
            word_count=word_count,
            approx_token_count=round(
                word_count * WORDS_TO_TOKENS_FACTOR
            ),
            split_reason=_split_reason(
                chunk_count, len(items), word_count
            ),
            metadata=dict(segment.get("metadata", {})),
        )

        chunks.append(chunk)

    return chunks


def _chunk_to_dict(chunk: Chunk) -> dict:

    return {
        "chunk_id": chunk.chunk_id,
        "segment_id": chunk.segment_id,
        "document_id": chunk.document_id,
        "filename": chunk.filename,
        "chunk_index": chunk.chunk_index,
        "start_page": chunk.start_page,
        "end_page": chunk.end_page,
        "page_count": chunk.page_count,
        "chapter": chunk.chapter,
        "section": chunk.section,
        "subsection": chunk.subsection,
        "text": chunk.text,
        "word_count": chunk.word_count,
        "approx_token_count": chunk.approx_token_count,
        "split_reason": chunk.split_reason,
        "metadata": chunk.metadata,
    }


def process_segment_file(segment_path: Path) -> list[dict]:

    with open(segment_path, "r", encoding="utf-8") as file:
        segment = json.load(file)

    chunks = chunk_segment(segment)

    output_dir = CHUNKS_DIR / segment["document_id"]
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for chunk in chunks:

        data = _chunk_to_dict(chunk)

        output_path = output_dir / f"{chunk.chunk_id}.json"

        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

        results.append(data)

    return results


def process_all_segments() -> list[dict]:

    if not SEGMENTS_DIR.exists():
        return []

    all_chunks = []

    for segment_path in sorted(SEGMENTS_DIR.rglob("*.json")):

        all_chunks.extend(
            process_segment_file(segment_path)
        )

    return all_chunks

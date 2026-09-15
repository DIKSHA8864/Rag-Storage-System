"""
Turns whatever an End User submits (pasted text, or a PDF/DOCX/TXT
file) into embedded chunks, ready to compare against the knowledge
base (app/analysis/matcher.py) - Phase 2 of the End User pipeline.
Audio/video input is Phase 3, not implemented here.

Deliberately reuses the exact same extraction -> segmentation ->
chunking -> embedding functions Owner uploads go through
(app/extraction/extractor_manager.py, app/segmentation/, app/embeddings/)
rather than a parallel implementation, so an End User's submission is
processed identically to how the knowledge base itself was built -
the whole point of comparing "like with like".

The one difference from the Owner pipeline: nothing here is written
to storage/processed, storage/segments, storage/chunks, or pgvector.
An End User's submission is not part of the protected document
repository and must not become part of it - it exists only for the
duration of one request, as return values, and any temp file created
along the way is deleted immediately after extraction.
"""

import tempfile
from pathlib import Path

from app.embeddings.embedding_manager import embed_texts
from app.extraction.extractor_manager import extract_document
from app.segmentation.chunker import chunk_segment
from app.segmentation.logical_segmenter import segment_document
from app.segmentation.segmentation_manager import segment_to_dict
from config.settings import get_settings


def _extract_from_bytes(filename: str, data: bytes) -> dict:
    """
    Run the standard extractor (extract_pdf/extract_docx/extract_txt,
    selected by extension - see extract_document()) against in-memory
    bytes. Those extractors read from a real Path, so this writes to a
    throwaway temp file just long enough to extract, then deletes it -
    no different, from the extractor's point of view, than an Owner's
    uploaded file, but nothing here ever lands under storage/.
    """

    suffix = Path(filename).suffix.lower()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(data)
        tmp_path = Path(tmp_file.name)

    try:
        document = extract_document(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # extract_document() sets "filename" from the temp path (a random
    # name) - restore the End User's actual filename so it's what
    # eventually shows up in the report, not a tmp* name.
    document["filename"] = filename

    return document


def is_supported_submission(filename: str) -> bool:
    """
    PDF/DOCX/TXT only, same as Owner uploads (ALLOWED_EXTENSIONS /
    config/settings.py) - legacy .doc and audio/video are out of scope
    for now (audio/video is Phase 3; .doc was never supported by
    app/extraction/, only .docx).
    """

    return Path(filename).suffix.lower() in get_settings().allowed_extensions_set


def process_submission(filename: str, data: bytes) -> list[dict]:
    """
    Extract, segment, chunk, and embed one End User submission.

    Returns a list of ephemeral chunk dicts (chunk_index, text,
    chapter, section, start_page, end_page, embedding) - never
    persisted anywhere, safe to discard after the comparison
    (app/analysis/matcher.py) that consumes them runs.
    """

    document = _extract_from_bytes(filename, data)
    segments = segment_document(document)

    chunks = []
    for segment in segments:
        chunks.extend(chunk_segment(segment_to_dict(segment)))

    if not chunks:
        return []

    embeddings = embed_texts([chunk.text for chunk in chunks])

    return [
        {
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "chapter": chunk.chapter,
            "section": chunk.section,
            "start_page": chunk.start_page,
            "end_page": chunk.end_page,
        }
        | {"embedding": embedding}
        for chunk, embedding in zip(chunks, embeddings)
    ]


def process_text_submission(text: str) -> list[dict]:
    """
    Same pipeline as process_submission(), for pasted text rather than
    an uploaded file - wraps it as a synthetic .txt "file" so it goes
    through the identical extract -> segment -> chunk -> embed path
    (extract_txt()'s blank-line paragraph splitting still applies).
    """

    return process_submission("submission.txt", text.encode("utf-8"))

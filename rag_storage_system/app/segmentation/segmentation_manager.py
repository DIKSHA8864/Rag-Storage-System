import json
from pathlib import Path

from app.segmentation.logical_segmenter import (
    segment_document,
)
from app.segmentation.models import LogicalSegment
from config.settings import get_settings

_settings = get_settings()

PROCESSED_DIR = _settings.resolve(_settings.processed_storage_path)
SEGMENTS_DIR = _settings.resolve(_settings.segments_storage_path)


def segment_to_dict(segment: LogicalSegment) -> dict:
    """
    The JSON-serializable shape one LogicalSegment (Phase 3-4 - see
    app/segmentation/logical_segmenter.py) is written/read as. Shared
    by process_extracted_document() below (which writes it to
    storage/segments/) and app/analysis/ingestion.py (which feeds it
    straight into app/segmentation/chunker.py:chunk_segment() for an
    End User's submitted document - never written to disk, since that
    submission isn't part of the protected knowledge base).
    """

    return {
        "segment_id":
            segment.segment_id,

        "document_id":
            segment.document_id,

        "filename":
            segment.filename,

        "start_page":
            segment.start_page,

        "end_page":
            segment.end_page,

        "page_count":
            segment.page_count,

        "chapter":
            segment.chapter,

        "section":
            segment.section,

        "subsection":
            segment.subsection,

        "text":
            segment.text,

        "structural_elements": [
            {
                "element_type":
                    item.element_type,

                "text":
                    item.text,

                "page_number":
                    item.page_number,

                "level":
                    item.level,
            }

            for item
            in segment.structural_elements
        ],

        "metadata":
            segment.metadata,
    }


def process_extracted_document(
    extracted_path: Path,
) -> list[dict]:

    with open(
        extracted_path,
        "r",
        encoding="utf-8",
    ) as file:

        document = json.load(file)

    segments = segment_document(
        document
    )

    output_dir = (
        SEGMENTS_DIR
        / (
            document.get("document_id")
            or Path(document["filename"]).stem
        )
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    results = []

    for segment in segments:

        output_path = (
            output_dir
            / f"{segment.segment_id}.json"
        )

        data = segment_to_dict(segment)
        # Carried into every chunk's metadata (chunker copies segment
        # metadata) - see app/embeddings/embedding_manager.py's
        # embedding_input() for how it shapes what gets embedded.
        data["metadata"] = {
            **(data.get("metadata") or {}),
            "category": document.get("category"),
            "summary": document.get("summary"),
        }

        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

        results.append(data)

    return results


def process_all_documents():

    if not PROCESSED_DIR.exists():

        return []

    all_segments = []

    for extracted_path in (
        PROCESSED_DIR.rglob(
            "extracted.json"
        )
    ):

        segments = (
            process_extracted_document(
                extracted_path
            )
        )

        all_segments.extend(
            segments
        )

    return all_segments
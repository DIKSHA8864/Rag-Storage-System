"""
Segmentation tests (Phase 4), porting the manual checks
scripts/test_segmentation.py used to only print, into real assertions.
"""

from app.segmentation.logical_segmenter import segment_document
from app.segmentation.segmentation_manager import process_extracted_document
from app.segmentation.structure_detector import detect_structure


# ---------------------------------------------------------------------
# structure_detector
# ---------------------------------------------------------------------


def test_detect_structure_finds_chapter():
    elements = detect_structure("CHAPTER 1: INTRODUCTION", page_number=1)
    assert len(elements) == 1
    assert elements[0].element_type == "chapter"


def test_detect_structure_finds_numbered_section():
    elements = detect_structure("1.2. Plaintiffs' Evaluation of Claims", page_number=2)
    assert len(elements) == 1
    assert elements[0].element_type == "section"


def test_detect_structure_finds_lettered_subsection():
    elements = detect_structure("A. Background", page_number=3)
    assert len(elements) == 1
    assert elements[0].element_type == "subsection"


def test_detect_structure_ignores_plain_prose():
    elements = detect_structure("This is just a regular sentence.", page_number=1)
    assert elements == []


# ---------------------------------------------------------------------
# segment_document()
# ---------------------------------------------------------------------


def _document(pages):
    return {
        "filename": "policy.txt",
        "file_type": "txt",
        "page_count": len(pages),
        "pages": pages,
    }


def test_segment_document_skips_title_page():
    document = _document(
        [
            {"page_number": 1, "text": "CHAPTER 1: INTRODUCTION\n1.1. Background"},
            {"page_number": 2, "text": "Actual content starts here."},
        ]
    )

    segments = segment_document(document)

    assert len(segments) == 1
    assert segments[0].start_page == 2
    assert "Actual content" in segments[0].text


def test_segment_document_splits_on_new_section():
    document = _document(
        [
            {"page_number": 1, "text": "1.1. Background\nFirst section content."},
            {"page_number": 2, "text": "1.2. Next Topic\nSecond section content."},
        ]
    )

    segments = segment_document(document)

    assert len(segments) == 2
    assert segments[0].section == "1.1. Background"
    assert segments[0].end_page == 1
    assert segments[1].section == "1.2. Next Topic"
    assert segments[1].start_page == 2


def test_segment_document_merges_repeated_running_header():
    document = _document(
        [
            {"page_number": 1, "text": "1.1. Background\nFirst page content."},
            {"page_number": 2, "text": "1.1. Background\nSecond page, same section."},
        ]
    )

    segments = segment_document(document)

    assert len(segments) == 1
    assert segments[0].start_page == 1
    assert segments[0].end_page == 2


def test_segment_document_empty_pages_returns_no_segments():
    assert segment_document(_document([])) == []


def test_segment_document_skips_blank_pages():
    document = _document(
        [
            {"page_number": 1, "text": ""},
            {"page_number": 2, "text": "Some real content."},
        ]
    )

    segments = segment_document(document)
    assert len(segments) == 1
    assert segments[0].start_page == 2


# ---------------------------------------------------------------------
# segmentation_manager.process_extracted_document() - writes segment
# JSON files, one per segment, mirroring extraction's folder layout.
# ---------------------------------------------------------------------


def test_process_extracted_document_writes_segment_files(tmp_path, monkeypatch):
    from app.segmentation import segmentation_manager

    segments_dir = tmp_path / "segments"
    monkeypatch.setattr(segmentation_manager, "SEGMENTS_DIR", segments_dir)

    extracted_path = tmp_path / "extracted.json"
    extracted_path.write_text(
        '{"filename": "policy.txt", "file_type": "txt", "page_count": 1, '
        '"pages": [{"page_number": 1, "text": "Some real content."}]}',
        encoding="utf-8",
    )

    results = segmentation_manager.process_extracted_document(extracted_path)

    assert len(results) == 1
    output_files = list((segments_dir / "policy").glob("*.json"))
    assert len(output_files) == 1

"""Tests for app/multimodal/document_processor.py, image_processor.py, audio_processor.py, video_processor.py, and pipeline.py's dispatch/ZIP orchestration."""

import io
import zipfile

from app.multimodal.audio_processor import process_audio
from app.multimodal.document_processor import process_document
from app.multimodal.image_processor import process_image
from app.multimodal.models import ProcessingStatus
from app.multimodal.pipeline import process_uploaded_input
from app.multimodal.video_processor import process_video


def test_process_document_extracts_txt_text():
    result = process_document("notes.txt", b"Hello world.\n\nSecond paragraph.")

    assert "Hello world." in result.text
    assert "Second paragraph." in result.text
    assert result.is_mock is False


def test_process_image_returns_ocr_and_caption_mock_results():
    results = process_image("scan.png", b"\x89PNG fake bytes")

    content_types = {r.content_type for r in results}
    assert content_types == {"ocr_text", "caption"}
    assert all(r.is_mock for r in results)


def test_process_audio_returns_mock_transcript():
    result = process_audio("call.mp3", b"fake audio bytes")

    assert result.content_type == "transcript"
    assert result.is_mock is True


def test_process_video_returns_mock_transcript():
    result = process_video("clip.mp4", b"fake video bytes")

    assert result.content_type == "transcript"
    assert result.is_mock is True


def test_pipeline_processes_a_plain_text_upload():
    result = process_uploaded_input("notes.txt", b"Some intake notes.")

    assert result.status == ProcessingStatus.COMPLETED
    assert len(result.extracted) == 1
    assert "Some intake notes." in result.extracted[0].text


def test_pipeline_rejects_unsupported_extension():
    result = process_uploaded_input("virus.exe", b"anything")

    assert result.status == ProcessingStatus.FAILED
    assert result.status_detail is not None


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_pipeline_processes_every_supported_member_of_a_zip():
    zip_bytes = _make_zip({"a.txt": b"first file", "b.txt": b"second file"})

    result = process_uploaded_input("bundle.zip", zip_bytes)

    assert result.status == ProcessingStatus.COMPLETED
    member_names = {item.archive_member_filename for item in result.extracted}
    assert member_names == {"a.txt", "b.txt"}


def test_pipeline_marks_zip_partial_when_one_member_is_unsupported():
    zip_bytes = _make_zip({"a.txt": b"ok file", "b.exe": b"not supported"})

    result = process_uploaded_input("bundle.zip", zip_bytes)

    assert result.status == ProcessingStatus.PARTIAL
    assert "b.exe" in result.status_detail
    assert len(result.extracted) == 1

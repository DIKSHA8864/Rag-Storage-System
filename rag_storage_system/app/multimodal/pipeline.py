"""
Entry point for Client-intake multimodal processing
(app/jobs/intake_processing.py calls this from the background worker).
Dispatches by extension to the right processor
(document_processor/image_processor/audio_processor/video_processor),
or to zip_processor for a ZIP - each member of a ZIP is dispatched the
same way, one level deep (nested ZIPs are rejected - see
zip_processor.py).
"""

import tempfile
from pathlib import Path

from app.multimodal.audio_processor import process_audio
from app.multimodal.document_processor import process_document
from app.multimodal.image_processor import process_image
from app.multimodal.models import (
    ExtractedContent,
    MediaType,
    ProcessedInput,
    ProcessingStatus,
    media_type_for_extension,
)
from app.multimodal.video_processor import process_video
from app.multimodal.zip_processor import ZipValidationError, extract_zip_members


def _process_single_file(filename: str, data: bytes) -> list[ExtractedContent]:
    extension = Path(filename).suffix.lower()
    media_type = media_type_for_extension(extension)

    if media_type == MediaType.DOCUMENT:
        return [process_document(filename, data)]
    if media_type == MediaType.IMAGE:
        return process_image(filename, data)
    if media_type == MediaType.AUDIO:
        return [process_audio(filename, data)]
    if media_type == MediaType.VIDEO:
        return [process_video(filename, data)]

    raise ValueError(f"Unsupported file type for multimodal processing: {extension}")


def process_uploaded_input(filename: str, data: bytes) -> ProcessedInput:
    """
    Process one uploaded file end to end and return every piece of
    extracted content, tagged with the archive member it came from
    (None for a non-ZIP upload). A failure within a single ZIP member
    never aborts the whole ZIP - that member is skipped and recorded in
    status_detail, so one bad file does not lose the rest.
    """

    extension = Path(filename).suffix.lower()
    media_type = media_type_for_extension(extension)

    if media_type != MediaType.ARCHIVE:
        try:
            extracted = _process_single_file(filename, data)
        except Exception as exc:
            return ProcessedInput(status=ProcessingStatus.FAILED, extracted=[], status_detail=str(exc))

        return ProcessedInput(status=ProcessingStatus.COMPLETED, extracted=extracted)

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            members = extract_zip_members(data, Path(tmp_dir))
        except ZipValidationError as exc:
            return ProcessedInput(status=ProcessingStatus.FAILED, extracted=[], status_detail=str(exc))

        all_extracted: list[ExtractedContent] = []
        failures: list[str] = []

        for member_name, member_path in members:
            member_extension = Path(member_name).suffix.lower()

            if media_type_for_extension(member_extension) is None:
                failures.append(f"{member_name}: unsupported file type")
                continue

            try:
                member_bytes = member_path.read_bytes()
                member_extracted = _process_single_file(member_name, member_bytes)
            except Exception as exc:
                failures.append(f"{member_name}: {exc}")
                continue

            for item in member_extracted:
                item.archive_member_filename = member_name
                all_extracted.append(item)

        if not all_extracted:
            return ProcessedInput(
                status=ProcessingStatus.FAILED,
                extracted=[],
                status_detail="; ".join(failures) or "ZIP contained no processable files.",
            )

        if failures:
            return ProcessedInput(status=ProcessingStatus.PARTIAL, extracted=all_extracted, status_detail="; ".join(failures))

        return ProcessedInput(status=ProcessingStatus.COMPLETED, extracted=all_extracted)

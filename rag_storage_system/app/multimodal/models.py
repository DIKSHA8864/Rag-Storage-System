"""
Shared types for app/multimodal/ - the pluggable multimodal input
pipeline for Phase 3 Client intake (documents/images/audio/video/ZIP).
Mirrors app/analysis/models.py's role: plain dataclasses/enums shared
across the pipeline and its provider interfaces, no provider-specific
logic here.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MediaType(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVE = "archive"


class ProcessingStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # some ZIP members succeeded, others failed


_EXTENSION_MEDIA_TYPES: dict[str, MediaType] = {
    ".pdf": MediaType.DOCUMENT,
    ".docx": MediaType.DOCUMENT,
    ".txt": MediaType.DOCUMENT,
    ".png": MediaType.IMAGE,
    ".jpg": MediaType.IMAGE,
    ".jpeg": MediaType.IMAGE,
    ".tiff": MediaType.IMAGE,
    ".bmp": MediaType.IMAGE,
    ".mp3": MediaType.AUDIO,
    ".wav": MediaType.AUDIO,
    ".m4a": MediaType.AUDIO,
    ".mp4": MediaType.VIDEO,
    ".mov": MediaType.VIDEO,
    ".avi": MediaType.VIDEO,
    ".zip": MediaType.ARCHIVE,
}


def media_type_for_extension(extension: str) -> Optional[MediaType]:
    return _EXTENSION_MEDIA_TYPES.get(extension.lower())


@dataclass
class ExtractedContent:
    """One piece of text pulled out of an uploaded input (or one ZIP member)."""

    content_type: str  # "text" | "ocr_text" | "transcript" | "caption" | "frame_caption"
    text: str
    provider: str
    is_mock: bool
    archive_member_filename: Optional[str] = None


@dataclass
class ProcessedInput:
    """
    process_uploaded_input()'s full result for one uploaded_input row -
    a ZIP produces one ExtractedContent per member (or per failure)
    instead of one, so a partial ZIP failure is still traceable member
    by member.
    """

    status: ProcessingStatus
    extracted: list[ExtractedContent]
    status_detail: Optional[str] = None

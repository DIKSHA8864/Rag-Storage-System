"""
Secure ZIP extraction for Client intake - a Client may submit a ZIP of
several documents/images/audio files in one upload. Every member path
goes through app/security/path_security.py's resolve_within() before
anything is written to disk, the same zip-slip defense the rest of this
app already uses for category/filename input - a member named
"../../etc/passwd" or an absolute path can never escape the extraction
directory. Nested ZIPs (a ZIP inside a ZIP) are rejected outright
rather than recursed into, both to avoid unbounded recursion and
because it's a well-known zip-bomb vector.
"""

import io
import zipfile
from pathlib import Path

from app.security.path_security import resolve_within, sanitize_path_segment
from config.settings import get_settings


class ZipValidationError(ValueError):
    """A ZIP failed a safety check before any member was extracted."""


def extract_zip_members(zip_bytes: bytes, destination_dir: Path) -> list[tuple[str, Path]]:
    """
    Validate and extract every member of `zip_bytes` into
    `destination_dir` (created if needed), enforcing:
      - member count <= INTAKE_ZIP_MAX_FILES
      - total uncompressed size <= INTAKE_ZIP_MAX_TOTAL_SIZE_MB (checked
        BEFORE extracting anything, to reject a zip bomb up front)
      - no nested ZIP members
      - every extracted path stays inside destination_dir (zip-slip)

    Returns a list of (original_member_name, extracted_path) tuples,
    in the ZIP's own order. Raises ZipValidationError on any violation -
    nothing is extracted if validation fails.
    """

    settings = get_settings()
    destination_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]

        if len(members) > settings.intake_zip_max_files:
            raise ZipValidationError(
                f"ZIP contains {len(members)} files, exceeding the limit of "
                f"{settings.intake_zip_max_files}."
            )

        total_size = sum(info.file_size for info in members)
        if total_size > settings.intake_zip_max_total_size_bytes:
            raise ZipValidationError(
                f"ZIP's uncompressed contents ({total_size} bytes) exceed the "
                f"limit of {settings.intake_zip_max_total_size_bytes} bytes."
            )

        for info in members:
            if Path(info.filename).suffix.lower() == ".zip":
                raise ZipValidationError(f"Nested ZIP member is not allowed: {info.filename}")

        extracted: list[tuple[str, Path]] = []

        for info in members:
            safe_name = sanitize_path_segment(Path(info.filename).name)

            try:
                target_path = resolve_within(destination_dir, safe_name)
            except ValueError as exc:
                raise ZipValidationError(str(exc)) from exc

            # Avoid two differently-unsafe member names colliding after
            # sanitization, same approach as
            # LocalStorageBackend._avoid_collision().
            counter = 1
            while target_path.exists():
                target_path = destination_dir / f"{target_path.stem}_{counter}{target_path.suffix}"
                counter += 1

            with archive.open(info) as source, target_path.open("wb") as dest:
                dest.write(source.read())

            extracted.append((info.filename, target_path))

    return extracted

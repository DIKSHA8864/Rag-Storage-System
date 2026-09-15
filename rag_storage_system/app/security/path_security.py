"""
Small, dependency-free helpers to keep any filesystem path built
from untrusted input (a category name typed by an admin, an
uploaded filename) safely inside protected storage.

Used by the upload API, where a category or filename comes straight
from an HTTP request and must never be able to escape
storage/originals via things like "..", an absolute path, or a
path separator.
"""

import re
from pathlib import Path


_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9 ._-]+")


def sanitize_path_segment(value: str, fallback: str = "unnamed") -> str:
    """
    Reduce a single path segment (one folder or file name coming
    from a request) to safe characters only.
    """

    if not value:
        return fallback

    value = value.strip()

    # A literal separator would otherwise let one request argument
    # inject extra folder levels.
    value = value.replace("/", "_").replace("\\", "_")

    value = _UNSAFE_CHARACTERS.sub("_", value)

    value = value.strip(" ._")

    if not value or value in {".", ".."}:
        return fallback

    return value


def sanitize_category_path(value: str, fallback: str = "uncategorized") -> str:
    """
    Sanitize a category that may describe nested subfolders
    ("Contracts/2024/Signed"), by sanitizing each "/"-separated
    segment independently and rejoining them.

    Unlike sanitize_path_segment(), a literal "/" here is a
    subfolder delimiter, not an unsafe character to escape - but
    ".." and empty segments are still stripped so nesting can never
    be used to climb back out of protected storage.
    """

    if not value:
        return fallback

    raw_segments = value.replace("\\", "/").split("/")

    safe_segments = []

    for raw_segment in raw_segments:
        raw_segment = raw_segment.strip()

        if not raw_segment or raw_segment in {".", ".."}:
            continue

        safe_segments.append(sanitize_path_segment(raw_segment, fallback=""))

    safe_segments = [segment for segment in safe_segments if segment]

    if not safe_segments:
        return fallback

    return "/".join(safe_segments)


def resolve_within(base_dir: Path, *segments: str) -> Path:
    """
    Build base_dir joined with segments, and raise ValueError if the
    resulting path would resolve outside base_dir.

    This is a second, independent check on top of
    sanitize_path_segment() - defense in depth, not a replacement
    for it.
    """

    base = base_dir.resolve()

    target = base

    for segment in segments:
        target = target / segment

    target = target.resolve()

    if target != base and base not in target.parents:
        raise ValueError(
            f"Unsafe path detected outside of {base}: {target}"
        )

    return target

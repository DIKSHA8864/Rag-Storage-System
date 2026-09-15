from pathlib import Path

from config.settings import get_settings


def _allowed_extensions() -> set[str]:
    return get_settings().allowed_extensions_set


def _max_file_size() -> int:
    return get_settings().max_file_size_bytes


def validate_file(file_path: Path) -> tuple[bool, str]:
    """
    Validate a file before it enters protected storage.

    Returns:
        (True, "valid") if the file is valid.
        (False, reason) if the file is rejected.
    """

    if not file_path.exists():
        return False, "file_not_found"

    if not file_path.is_file():
        return False, "not_a_file"

    # Check extension
    extension = file_path.suffix.lower()

    if extension not in _allowed_extensions():
        return False, f"unsupported_extension:{extension}"

    # Check file size
    try:
        file_size = file_path.stat().st_size
    except OSError:
        return False, "cannot_read_file_information"

    if file_size == 0:
        return False, "empty_file"

    if file_size > _max_file_size():
        return False, "file_too_large"

    return True, "valid"


def validate_file_object(filename: str, size: int) -> tuple[bool, str]:
    """
    Same rules as validate_file(), but for an in-memory upload where
    we already have the filename and byte size and don't want to
    write a temp file to disk just to check them (needed now that
    storage_api.py hands bytes straight to the storage backend
    instead of going through a temp file first).

    Returns:
        (True, "valid") if the file is valid.
        (False, reason) if the file is rejected.
    """

    extension = Path(filename).suffix.lower()

    if extension not in _allowed_extensions():
        return False, f"unsupported_extension:{extension}"

    if size == 0:
        return False, "empty_file"

    if size > _max_file_size():
        return False, "file_too_large"

    return True, "valid"

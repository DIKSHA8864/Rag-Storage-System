"""
Upload validation for Client intake (app/api/intake_api.py) - same
pattern as app/ingestion/file_validator.py, against the wider
INTAKE_ALLOWED_EXTENSIONS/INTAKE_MAX_FILE_SIZE_MB (config/settings.py)
instead of the Owner knowledge-base's ALLOWED_EXTENSIONS/MAX_FILE_SIZE_MB.
"""

from pathlib import Path

from config.settings import get_settings


def validate_intake_file(filename: str, size: int) -> tuple[bool, str]:
    """
    Returns (True, "valid") if the file is acceptable for Client
    intake, or (False, reason) otherwise.
    """

    settings = get_settings()
    extension = Path(filename).suffix.lower()

    if extension not in settings.intake_allowed_extensions_set:
        return False, f"unsupported_extension:{extension}"

    if size == 0:
        return False, "empty_file"

    if size > settings.intake_max_file_size_bytes:
        return False, "file_too_large"

    return True, "valid"

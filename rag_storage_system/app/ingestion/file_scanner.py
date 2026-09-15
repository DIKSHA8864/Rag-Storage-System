from pathlib import Path

from app.ingestion.file_validator import validate_file


def scan_path(source_path: str) -> tuple[list[Path], list[dict]]:
    """
    Scan a file or folder recursively.

    Returns:
        valid_files:
            List of files that passed validation.

        rejected_files:
            List containing rejected file information.
    """

    source = Path(source_path).resolve()

    valid_files = []
    rejected_files = []

    if not source.exists():
        raise FileNotFoundError(
            f"Source path does not exist: {source}"
        )

    # Single file
    if source.is_file():
        is_valid, reason = validate_file(source)

        if is_valid:
            valid_files.append(source)
        else:
            rejected_files.append(
                {
                    "path": str(source),
                    "reason": reason,
                }
            )

        return valid_files, rejected_files

    # Folder
    for path in source.rglob("*"):

        if not path.is_file():
            continue

        is_valid, reason = validate_file(path)

        if is_valid:
            valid_files.append(path)
        else:
            rejected_files.append(
                {
                    "path": str(path),
                    "reason": reason,
                }
            )

    return valid_files, rejected_files
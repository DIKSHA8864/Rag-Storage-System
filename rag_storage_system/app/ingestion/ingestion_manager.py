from pathlib import Path

from app.ingestion.file_scanner import scan_path
from app.metadata import get_metadata_repository
from app.metadata.models import DocumentStatus
from app.storage import get_storage_backend

UNCATEGORIZED = "uncategorized"


def _category_for(source_file: Path, source_root: Path) -> str:
    """
    Derive a category (folder) from a source file's position relative
    to the root being ingested, so a directory ingest preserves its
    folder structure as categories/subcategories.
    """

    try:
        relative_path = source_file.relative_to(source_root)
    except ValueError:
        return UNCATEGORIZED

    parent = relative_path.parent

    if parent == Path("."):
        return UNCATEGORIZED

    return parent.as_posix()


def ingest(source_path: str) -> dict:
    """
    Ingest a file or folder into protected storage via the active
    StorageBackend (the same one app/api/storage_api.py uses), so a
    CLI ingest and an API upload always end up validated and stored
    the same way regardless of which backend is configured.
    """

    storage_backend = get_storage_backend()
    metadata_repository = get_metadata_repository()

    source = Path(source_path).resolve()

    valid_files, rejected_files = scan_path(str(source))

    successful_files = []
    failed_files = []

    # If source is a folder, preserve its structure as categories.
    source_root = source if source.is_dir() else source.parent

    for source_file in valid_files:

        category = _category_for(source_file, source_root)

        try:
            with source_file.open("rb") as file_obj:
                result = storage_backend.save(category, source_file.name, file_obj)

            extension = Path(result["stored_filename"]).suffix.lower()

            metadata_repository.upsert_document(
                category=result["category"],
                filename=result["stored_filename"],
                extension=extension,
                size=result["size"],
                sha256=result["sha256"],
                status=DocumentStatus.UPLOADED.value,
            )

            successful_files.append(
                {
                    "source": str(source_file),
                    "category": result["category"],
                    "filename": result["stored_filename"],
                    "extension": extension,
                    "size": result["size"],
                    "sha256": result["sha256"],
                }
            )

        except Exception as exc:

            failed_files.append(
                {
                    "source": str(source_file),
                    "error": str(exc),
                }
            )

    return {
        "source": str(source),
        "successful": successful_files,
        "rejected": rejected_files,
        "failed": failed_files,
        "total_found": len(valid_files) + len(rejected_files),
        "total_stored": len(successful_files),
        "total_rejected": len(rejected_files),
        "total_failed": len(failed_files),
    }

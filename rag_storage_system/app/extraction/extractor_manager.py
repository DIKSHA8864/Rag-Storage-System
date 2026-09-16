import json
import tempfile
from pathlib import Path

from app.extraction.pdf_extractor import extract_pdf
from app.extraction.docx_extractor import extract_docx
from app.extraction.txt_extractor import extract_txt
from config.settings import get_settings

_settings = get_settings()

# Documents are read through the StorageBackend, not from a disk
# path - only the derived extraction output still lands on disk.
PROCESSED_DIR = _settings.resolve(_settings.processed_storage_path)

SUPPORTED_EXTENSIONS = _settings.allowed_extensions_set


def extract_document(file_path: str | Path) -> dict:
    """
    Select the correct extractor based on file extension.
    """

    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Document does not exist: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Path is not a file: {path}"
        )

    extension = path.suffix.lower()

    if extension == ".pdf":
        result = extract_pdf(path)

    elif extension == ".docx":
        result = extract_docx(path)

    elif extension == ".txt":
        result = extract_txt(path)

    else:
        raise ValueError(
            f"Unsupported document type: {extension}"
        )

    result["source_path"] = str(path)

    return result


def extract_all_documents(backend=None) -> list[dict]:
    """
    Extract every supported document in protected storage and save
    each result to storage/processed/<category>/<stem>/extracted.json,
    mirroring the category structure (so a category in storage becomes
    the same folder under storage/processed).

    Documents are enumerated and read through the configured
    StorageBackend (app/storage/), NOT by walking storage/originals
    directly - otherwise POST /process would silently find nothing
    whenever STORAGE_BACKEND=s3, because the files live in a bucket
    rather than on local disk.

    The individual extractors (PyMuPDF, python-docx) need a real
    filesystem path and seek freely, so each document is streamed to a
    temporary file, extracted, and the temp file deleted - never left
    behind, even when extraction raises.

    `backend` defaults to the configured StorageBackend; pass one
    explicitly to extract from a specific store (the test suite does
    this to stay inside its tmp_path).

    This is the same save layout scripts/test_extraction.py already
    uses; it exists here too as a reusable entry point (the upload
    API calls this directly instead of duplicating the logic).
    """

    if backend is None:
        from app.storage import get_storage_backend

        backend = get_storage_backend()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    for document in backend.list_files():

        filename = document["filename"]
        category = document["category"]
        extension = Path(filename).suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            continue

        output_directory = PROCESSED_DIR / category / Path(filename).stem
        output_path = output_directory / "extracted.json"

        try:
            with backend.open_file(category, filename) as source:
                payload = source.read()

            with tempfile.NamedTemporaryFile(
                suffix=extension, delete=False
            ) as temporary:
                temporary.write(payload)
                temporary_path = Path(temporary.name)

            try:
                extracted = extract_document(temporary_path)
            finally:
                temporary_path.unlink(missing_ok=True)

            # The temp path is an implementation detail - record where
            # the document actually lives instead.
            extracted["source_path"] = f"{category}/{filename}"

            output_directory.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as file:
                json.dump(
                    extracted, file, indent=2, ensure_ascii=False
                )

            results.append(
                {
                    "filename": filename,
                    "category": category,
                    "status": "extracted",
                    "output_path": str(output_path),
                }
            )

        except Exception as exc:

            results.append(
                {
                    "filename": filename,
                    "category": category,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return results
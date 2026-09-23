import json
from pathlib import Path

from app.extraction.pdf_extractor import extract_pdf
from app.extraction.docx_extractor import extract_docx
from app.extraction.txt_extractor import extract_txt
from config.settings import get_settings

_settings = get_settings()

ORIGINALS_DIR = _settings.resolve(_settings.original_storage_path)
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


def extract_all_documents() -> list[dict]:
    """
    Extract every supported document under storage/originals and
    save each result to storage/processed/<relative-path>/extracted.json,
    mirroring the source folder structure (so a category folder
    under storage/originals becomes the same category folder under
    storage/processed).

    This is the same save layout scripts/test_extraction.py already
    uses; it exists here too as a reusable entry point (the upload
    API calls this directly instead of duplicating the logic).
    """

    if not ORIGINALS_DIR.exists():
        return []

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    for file_path in sorted(ORIGINALS_DIR.rglob("*")):

        if not file_path.is_file():
            continue

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        relative_path = file_path.relative_to(ORIGINALS_DIR)

        category = (
            relative_path.parent.as_posix()
            if relative_path.parent != Path(".")
            else "uncategorized"
        )

        output_directory = (
            PROCESSED_DIR
            / relative_path.parent
            / relative_path.stem
        )

        output_path = output_directory / "extracted.json"

        try:
            extracted = extract_document(file_path)

            output_directory.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as file:
                json.dump(
                    extracted, file, indent=2, ensure_ascii=False
                )

            results.append(
                {
                    "filename": file_path.name,
                    "category": category,
                    "status": "extracted",
                    "output_path": str(output_path),
                    # Only PDFs report this (see app/extraction/pdf_extractor.py's
                    # OCR fallback) - 0/absent for every other extractor.
                    "ocr_pages_used": extracted.get("ocr_pages_used", 0),
                }
            )

        except Exception as exc:

            results.append(
                {
                    "filename": file_path.name,
                    "category": category,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return results
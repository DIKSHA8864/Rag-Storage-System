import json
import re
from pathlib import Path

from app.extraction.pdf_extractor import extract_pdf
from app.extraction.docx_extractor import extract_docx
from app.extraction.txt_extractor import extract_txt
from config.settings import get_settings

_settings = get_settings()

ORIGINALS_DIR = _settings.resolve(_settings.original_storage_path)
PROCESSED_DIR = _settings.resolve(_settings.processed_storage_path)

SUPPORTED_EXTENSIONS = _settings.allowed_extensions_set

# Owner-vault uploads live under storage/originals/tenant-<id>/<category>/...
# (app/api/storage_api.py's _tenant_storage_category()) - real physical
# per-tenant partitioning, not just a documents.tenant_id column. A
# top-level segment that doesn't match this pattern predates Step 24's
# tenant-partitioning migration and is treated as belonging to tenant 1
# (the seeded Default Organization), the same "everything defaults to
# tenant 1" convention used everywhere else in the multi-tenancy retrofit.
_TENANT_DIR_RE = re.compile(r"^tenant-(\d+)$")


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
    storage/processed) - including the tenant-<id> top-level segment,
    so storage/processed stays just as tenant-partitioned on disk as
    storage/originals.

    Each result's "category" is the clean, tenant-prefix-stripped
    category (what the `documents` table and every API response
    actually shows); "tenant_id" is parsed from the physical path so
    app/jobs/processing.py can update each document's status/chunks
    under its own real tenant, never another one's - see
    app/api/storage_api.py's _tenant_storage_category().

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
        relative_parts = relative_path.parent.parts

        tenant_id = 1
        category_parts = relative_parts
        if relative_parts:
            tenant_match = _TENANT_DIR_RE.match(relative_parts[0])
            if tenant_match:
                tenant_id = int(tenant_match.group(1))
                category_parts = relative_parts[1:]

        category = "/".join(category_parts) if category_parts else "uncategorized"

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
                    "tenant_id": tenant_id,
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
                    "tenant_id": tenant_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return results
"""
Document extraction for Client intake (PDF/DOCX/TXT) - reuses the exact
same extractor dispatch the Owner pipeline uses
(app/extraction/extractor_manager.py's extract_document()) via a
throwaway temp file, the identical approach app/analysis/ingestion.py
already uses for End User /compare submissions.
"""

import tempfile
from pathlib import Path

from app.extraction.extractor_manager import extract_document
from app.multimodal.models import ExtractedContent


def process_document(filename: str, data: bytes) -> ExtractedContent:
    suffix = Path(filename).suffix.lower()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(data)
        tmp_path = Path(tmp_file.name)

    try:
        extracted = extract_document(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    text = "\n\n".join(page["text"] for page in extracted["pages"] if page.get("text"))

    return ExtractedContent(content_type="text", text=text, provider="document_extractor", is_mock=False)

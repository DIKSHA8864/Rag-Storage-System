"""
Removing a document's derived pipeline artifacts.

Deleting a document has to clear more than the file and its metadata
row. Each processing run leaves output in four places, and the chunks
directory is the dangerous one: POST /process re-embeds whatever chunk
JSON it finds, so leaving it behind silently re-inserts the very
pgvector rows the delete just removed - the delete appears to work,
then undoes itself on the next process run.

    storage/processed/<category>/<stem>/   extraction output
    storage/segments/<stem>/               logical segments
    storage/chunks/<stem>/                 embedding-sized chunks
    storage/embeddings/<stem>/             vectors

Only the first is namespaced by category. The other three are keyed on
the filename stem alone, so two documents with the same name in
different categories share those directories. Those are therefore kept
whenever any other stored document still has the same stem - POST
/process rebuilds everything anyway, so a stale copy is corrected on
the next run rather than taking a live document's data with it.

That sharing is a real modelling flaw, not something this module
fixes; document_id should be namespaced by category (or hashed from
category + filename) before the Blueprint's per-matter isolation
arrives, since matter-scoped documents must never collide.
"""

import shutil
from pathlib import Path

from app.security.path_security import resolve_within, sanitize_category_path
from config.settings import get_settings

_settings = get_settings()

PROCESSED_DIR = _settings.resolve(_settings.processed_storage_path)
SEGMENTS_DIR = _settings.resolve(_settings.segments_storage_path)
CHUNKS_DIR = _settings.resolve(_settings.chunks_storage_path)
EMBEDDINGS_DIR = _settings.resolve(_settings.embeddings_storage_path)


def _remove(path: Path) -> bool:
    if not path.is_dir():
        return False

    shutil.rmtree(path)
    return True


def purge_document_artifacts(category: str, filename: str, backend) -> dict:
    """
    Remove the derived artifacts of one already-deleted document.

    `backend` is the StorageBackend, consulted to find out whether any
    surviving document still shares this one's filename stem. Call
    this AFTER the document has been removed from storage, so it no
    longer counts as its own collision.

    Returns which of the four locations were actually removed.
    """

    safe_category = sanitize_category_path(category)
    stem = Path(filename).stem

    removed = {
        "processed": _remove(
            resolve_within(PROCESSED_DIR, *safe_category.split("/"), stem)
        )
    }

    stem_still_in_use = any(
        Path(document["filename"]).stem == stem for document in backend.list_files()
    )

    for label, base in (
        ("segments", SEGMENTS_DIR),
        ("chunks", CHUNKS_DIR),
        ("embeddings", EMBEDDINGS_DIR),
    ):
        removed[label] = (
            False if stem_still_in_use else _remove(resolve_within(base, stem))
        )

    return removed


def purge_category_artifacts(category: str, filenames: list[str], backend) -> None:
    """
    Same, for every document that was in a deleted category.

    `filenames` must be captured BEFORE the category is deleted -
    afterwards there is nothing left to list.
    """

    for filename in filenames:
        purge_document_artifacts(category, filename, backend)

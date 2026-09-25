"""
Mirror a source folder into one organization's library (Blueprint Phase 1:
"a designated Dropbox folder tree is the single source of truth. The
pipeline detects added, updated, and deleted files").

The source is any folder on the server: one that Dropbox's or Google
Drive's desktop app keeps in sync, or the local mirror
app/vault_sync/dropbox_source.py downloads through the Dropbox API.
Sub-folders become library folders (categories).

What a sync does, per file:
- new in the source        -> stored in the library (status Uploaded)
- changed (content hash)   -> replaced; its old chunks leave search at once
- gone from the source     -> deleted from the library and from search
A manifest (vault_sync_manifest) records every file the sync created, so
it only ever changes or deletes those - never a file uploaded by hand.
Processing (app/jobs/processing.py) then indexes the changes.

Safety: a missing, unreadable, or suddenly empty source folder (an
unmounted drive, a sync client that's signed out) must never wipe the
library - the sync refuses instead (see SyncRefused).
"""

import hashlib
import io
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.file_validator import validate_file_object
from app.security.virus_scan import ScannerUnavailable, scan_bytes
from app.security.path_security import sanitize_category_path, sanitize_path_segment

logger = logging.getLogger(__name__)

UNFILED_CATEGORY = "Unfiled"
# A run that would delete more than this share of the synced files (and
# more than MASS_DELETE_MIN of them) is refused unless explicitly allowed.
MASS_DELETE_SHARE = 0.5
MASS_DELETE_MIN = 10

_IGNORED_PREFIXES = (".", "~$")
_IGNORED_SUFFIXES = (".tmp", ".part", ".crdownload")


class SyncRefused(Exception):
    """The sync stopped before changing anything - the message says why."""


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    skipped: list[dict] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.deleted)


def _storage_category(category: str, tenant_id: int) -> str:
    """Same per-organization folder layout as app/api/storage_api.py's _tenant_storage_category()."""

    prefix = f"tenant-{tenant_id}"
    return f"{prefix}/{category}" if category else prefix


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_files(source_dir: Path) -> dict[str, Path]:
    """relative posix path -> file, skipping hidden/temporary files and hidden folders."""

    files: dict[str, Path] = {}
    for root, dirnames, filenames in os.walk(source_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(_IGNORED_PREFIXES) or name.lower().endswith(_IGNORED_SUFFIXES):
                continue
            path = Path(root) / name
            files[path.relative_to(source_dir).as_posix()] = path
    return files


def _library_location(relative_path: str) -> tuple[str, str]:
    parts = relative_path.split("/")
    category = sanitize_category_path("/".join(parts[:-1])) if len(parts) > 1 else UNFILED_CATEGORY
    return category, sanitize_path_segment(parts[-1])


def sync_folder(
    source_dir: Path,
    tenant_id: int,
    repository,
    storage_backend,
    vector_store,
    allow_mass_delete: bool = False,
) -> SyncResult:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise SyncRefused(f"The sync folder '{source_dir}' doesn't exist or isn't reachable - nothing was changed.")

    try:
        source = _source_files(source_dir)
    except OSError as exc:
        raise SyncRefused(f"The sync folder '{source_dir}' couldn't be read ({exc}) - nothing was changed.") from exc

    manifest = {row["source_path"]: row for row in repository.list_vault_manifest(tenant_id)}
    vanished = [path for path in manifest if path not in source]

    if manifest and not source:
        raise SyncRefused(
            f"The sync folder '{source_dir}' is empty but {len(manifest)} synced file(s) are in the library. "
            "This usually means the Dropbox/Drive folder isn't mounted or signed in - nothing was deleted."
        )
    if (
        not allow_mass_delete
        and len(vanished) > MASS_DELETE_MIN
        and len(vanished) > MASS_DELETE_SHARE * len(manifest)
    ):
        raise SyncRefused(
            f"{len(vanished)} of {len(manifest)} synced files disappeared from '{source_dir}' at once. "
            "Refusing to delete them automatically - run the sync with 'allow mass delete' if this is intended."
        )

    result = SyncResult()

    for relative_path, path in sorted(source.items()):
        category, filename = _library_location(relative_path)
        try:
            stat = path.stat()
        except OSError as exc:
            result.skipped.append({"path": relative_path, "reason": f"couldn't be read ({exc})"})
            continue

        is_valid, reason = validate_file_object(filename, stat.st_size)
        if not is_valid:
            result.skipped.append({"path": relative_path, "reason": reason})
            continue

        known = manifest.get(relative_path)
        if known and known["size"] == stat.st_size and float(known["mtime"]) == stat.st_mtime:
            result.unchanged += 1
            continue

        sha256 = _sha256(path)
        if known and known["sha256"] == sha256:
            repository.upsert_vault_manifest(tenant_id, relative_path, category, filename, sha256, stat.st_size, stat.st_mtime)
            result.unchanged += 1
            continue

        data = path.read_bytes()

        # Not recorded in the manifest when skipped, so the next run tries again.
        try:
            verdict = scan_bytes(data)
        except ScannerUnavailable as exc:
            result.skipped.append({"path": relative_path, "reason": f"not synced - {exc}"})
            continue
        if not verdict.clean:
            result.skipped.append({
                "path": relative_path,
                "reason": f"virus detected ({verdict.signature}) - not added; remove it from the synced folder",
            })
            continue

        if known:
            # Changed content: the old version must stop being citable now.
            vector_store.delete_document_chunks(known["category"], known["filename"], tenant_id)
            stored = storage_backend.replace(_storage_category(known["category"], tenant_id), known["filename"], io.BytesIO(data))
            repository.upsert_document(
                category=known["category"], filename=known["filename"], extension=Path(known["filename"]).suffix.lower(),
                size=stored["size"], sha256=stored["sha256"], status="Uploaded", tenant_id=tenant_id,
            )
            repository.upsert_vault_manifest(
                tenant_id, relative_path, known["category"], known["filename"], sha256, stat.st_size, stat.st_mtime
            )
            result.updated += 1
            continue

        if repository.get_document(category, filename, tenant_id=tenant_id) is not None:
            result.skipped.append({
                "path": relative_path,
                "reason": f"'{category}/{filename}' already exists in the library (uploaded by hand) - left untouched",
            })
            continue
        duplicate = repository.find_document_by_sha256(sha256, tenant_id)
        if duplicate is not None:
            result.skipped.append({
                "path": relative_path,
                "reason": f"same content is already in the library as '{duplicate['category']}/{duplicate['filename']}'",
            })
            continue

        repository.create_folder(category, tenant_id=tenant_id)
        stored = storage_backend.save(_storage_category(category, tenant_id), filename, io.BytesIO(data))
        repository.upsert_document(
            category=category, filename=stored["stored_filename"], extension=Path(filename).suffix.lower(),
            size=stored["size"], sha256=stored["sha256"], status="Uploaded", tenant_id=tenant_id,
        )
        repository.upsert_vault_manifest(
            tenant_id, relative_path, category, stored["stored_filename"], sha256, stat.st_size, stat.st_mtime
        )
        result.added += 1

    for relative_path in vanished:
        known = manifest[relative_path]
        vector_store.delete_document_chunks(known["category"], known["filename"], tenant_id)
        storage_backend.delete(_storage_category(known["category"], tenant_id), known["filename"])
        repository.delete_document(known["category"], known["filename"], tenant_id=tenant_id)
        repository.delete_vault_manifest(tenant_id, relative_path)
        result.deleted += 1

    logger.info(
        "Vault sync of '%s' for tenant %s: %d added, %d updated, %d deleted, %d unchanged, %d skipped",
        source_dir, tenant_id, result.added, result.updated, result.deleted, result.unchanged, len(result.skipped),
    )
    return result

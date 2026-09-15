"""
Local disk storage backend.

This is the free-demo backend: it stores files under
storage/originals/<category>/<filename> on the local filesystem,
exactly like the original storage_api.py did. The behavior (path
sanitization, collision avoidance, hashing, quarantine) is unchanged
from before - it has just been moved behind the StorageBackend
interface so app/api/storage_api.py no longer needs to know it's
talking to local disk at all.

When you're ready to pay for S3 / R2 / Azure Blob / GCS / MinIO,
write a sibling class (e.g. S3StorageBackend) that implements the
same StorageBackend methods, and switch get_storage_backend() in
app/storage/__init__.py to return it instead. Nothing in
storage_api.py should need to change.
"""

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO, Optional

from app.security.path_security import (
    resolve_within,
    sanitize_category_path,
    sanitize_path_segment,
)
from app.storage.base import StorageBackend


def _hash_file(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            sha256.update(chunk)
    return sha256.hexdigest()


def _avoid_collision(destination: Path) -> Path:
    if not destination.exists():
        return destination

    base = destination.stem
    suffix = destination.suffix
    counter = 1
    candidate = destination

    while candidate.exists():
        candidate = destination.parent / f"{base}_{counter}{suffix}"
        counter += 1

    return candidate


class LocalStorageBackend(StorageBackend):

    def __init__(self, originals_dir: Path, quarantine_dir: Path):
        self.originals_dir = originals_dir
        self.quarantine_dir = quarantine_dir
        self.originals_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def create_category(self, category: str) -> str:
        safe_category = sanitize_category_path(category)
        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))
        category_dir.mkdir(parents=True, exist_ok=True)
        return safe_category

    def list_categories(self) -> list[dict]:
        if not self.originals_dir.exists():
            return []

        categories = []

        for entry in sorted(self.originals_dir.rglob("*")):
            if not entry.is_dir():
                continue

            document_count = sum(1 for p in entry.rglob("*") if p.is_file())
            name = entry.relative_to(self.originals_dir).as_posix()

            categories.append(
                {"name": name, "document_count": document_count}
            )

        return categories

    def rename_category(self, old_name: str, new_name: str) -> str:
        safe_old = sanitize_category_path(old_name)
        safe_new = sanitize_category_path(new_name)

        old_dir = resolve_within(self.originals_dir, *safe_old.split("/"))
        new_dir = resolve_within(self.originals_dir, *safe_new.split("/"))

        if not old_dir.exists():
            raise FileNotFoundError(f"Category not found: {safe_old}")

        if new_dir.exists():
            raise ValueError(f"Category already exists: {safe_new}")

        new_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir.rename(new_dir)
        return safe_new

    def delete_category(self, category: str, force: bool = False) -> bool:
        safe_category = sanitize_category_path(category)
        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))

        if not category_dir.exists():
            return False

        has_files = any(p.is_file() for p in category_dir.rglob("*"))

        if has_files and not force:
            raise ValueError(
                f"Category '{safe_category}' is not empty. "
                "Pass force=True to delete it anyway."
            )

        shutil.rmtree(category_dir)
        return True

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def save(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        safe_category = sanitize_category_path(category)
        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))
        category_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = sanitize_path_segment(Path(filename).name)
        destination = _avoid_collision(category_dir / safe_filename)

        with destination.open("wb") as out:
            shutil.copyfileobj(file_obj, out)

        return {
            "stored_filename": destination.name,
            "category": safe_category,
            "size": destination.stat().st_size,
            "sha256": _hash_file(destination),
        }

    def replace(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        safe_category = sanitize_category_path(category)
        safe_filename = sanitize_path_segment(Path(filename).name)

        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))
        destination = resolve_within(category_dir, safe_filename)

        if not destination.exists():
            raise FileNotFoundError(
                f"Cannot replace - file not found: {safe_category}/{safe_filename}"
            )

        with destination.open("wb") as out:
            shutil.copyfileobj(file_obj, out)

        return {
            "stored_filename": destination.name,
            "category": safe_category,
            "size": destination.stat().st_size,
            "sha256": _hash_file(destination),
        }

    def delete(self, category: str, filename: str) -> bool:
        safe_category = sanitize_category_path(category)
        safe_filename = sanitize_path_segment(Path(filename).name)

        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))
        target = resolve_within(category_dir, safe_filename)

        if not target.exists():
            return False

        target.unlink()
        return True

    def exists(self, category: str, filename: str) -> bool:
        safe_category = sanitize_category_path(category)
        safe_filename = sanitize_path_segment(Path(filename).name)

        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))
        target = resolve_within(category_dir, safe_filename)

        return target.exists()

    def open_file(self, category: str, filename: str) -> BinaryIO:
        safe_category = sanitize_category_path(category)
        safe_filename = sanitize_path_segment(Path(filename).name)

        category_dir = resolve_within(self.originals_dir, *safe_category.split("/"))
        target = resolve_within(category_dir, safe_filename)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {safe_category}/{safe_filename}")

        return target.open("rb")

    def list_files(self, category: Optional[str] = None) -> list[dict]:
        if not self.originals_dir.exists():
            return []

        search_root = self.originals_dir

        if category:
            safe_category = sanitize_category_path(category)
            search_root = resolve_within(self.originals_dir, *safe_category.split("/"))

            if not search_root.exists():
                return []

        documents = []

        for path in sorted(search_root.rglob("*")):
            if not path.is_file():
                continue

            relative_path = path.relative_to(self.originals_dir)
            category_name = (
                relative_path.parent.as_posix()
                if len(relative_path.parts) > 1
                else "uncategorized"
            )

            documents.append(
                {
                    "filename": path.name,
                    "category": category_name,
                    "relative_path": str(relative_path),
                    "extension": path.suffix.lower(),
                    "size": path.stat().st_size,
                }
            )

        return documents

    # ------------------------------------------------------------------
    # Quarantine
    # ------------------------------------------------------------------

    def quarantine(self, category: str, filename: str, file_obj: BinaryIO) -> dict:
        safe_category = sanitize_category_path(category)
        safe_filename = sanitize_path_segment(Path(filename).name)

        quarantine_dir = resolve_within(self.quarantine_dir, *safe_category.split("/"))
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        destination = _avoid_collision(quarantine_dir / safe_filename)

        with destination.open("wb") as out:
            shutil.copyfileobj(file_obj, out)

        return {
            "stored_filename": destination.name,
            "category": safe_category,
            "size": destination.stat().st_size,
            "sha256": _hash_file(destination),
        }

"""
Pre-demo health check.

Verifies the environment is actually ready before you demo or grade
this: every configured storage folder exists and is writable, the
metadata database is reachable, and the embedding model can load.
Run it any time something feels off, and always right before a live
demo - a broken environment is much cheaper to catch here than
mid-demo.

Usage:
    python scripts/health_check.py
Exit code 0 if every check passes, 1 if any failed.
"""

import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_settings  # noqa: E402


def _check_folder_writable(label: str, path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".health_check_{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, f"{label}: writable ({path})"
    except OSError as exc:
        return False, f"{label}: NOT writable ({path}) - {exc}"


def _check_metadata_db(backend: str) -> tuple[bool, str]:
    try:
        from app.metadata import get_metadata_repository

        repository = get_metadata_repository()
        repository.list_folders()  # exercises an actual query, not just connect()
        return True, f"metadata DB ({backend}): reachable"
    except Exception as exc:
        return False, f"metadata DB ({backend}): NOT reachable - {exc}"


def _check_embedding_model(model_name: str) -> tuple[bool, str]:
    try:
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(model_name)
        return True, f"embedding model '{model_name}': loads OK"
    except Exception as exc:
        return False, f"embedding model '{model_name}': FAILED to load - {exc}"


def run_health_check() -> bool:
    settings = get_settings()

    checks: list[tuple[bool, str]] = []

    storage_paths = {
        "originals": settings.original_storage_path,
        "processed": settings.processed_storage_path,
        "metadata": settings.metadata_storage_path,
        "quarantine": settings.quarantine_storage_path,
        "segments": settings.segments_storage_path,
        "chunks": settings.chunks_storage_path,
        "embeddings": settings.embeddings_storage_path,
    }

    for label, relative_path in storage_paths.items():
        checks.append(_check_folder_writable(label, settings.resolve(relative_path)))

    checks.append(_check_metadata_db(settings.metadata_backend))
    checks.append(_check_embedding_model(settings.embedding_model))

    print("=" * 70)
    print("HEALTH CHECK")
    print("=" * 70)

    all_ok = True

    for ok, message in checks:
        print(f"{'OK  ' if ok else 'FAIL'} - {message}")
        all_ok = all_ok and ok

    print("=" * 70)
    print("All checks passed." if all_ok else "One or more checks FAILED.")

    return all_ok


if __name__ == "__main__":
    sys.exit(0 if run_health_check() else 1)

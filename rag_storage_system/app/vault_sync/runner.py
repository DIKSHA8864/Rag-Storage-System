"""
One vault-sync run end to end: refresh the Dropbox mirror (if the Dropbox
API is the source), mirror the source folder into the library
(folder_sync.py), index what changed (app/jobs/processing.py), and record
the outcome (vault_sync_runs) for the Vault page.

Runs in the background worker (POST /admin/vault-sync/run enqueues
run_vault_sync_job) or from scripts/vault_sync.py (once, or on a schedule
with --watch).
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.vault_sync.dropbox_source import DropboxError, DropboxMirror
from app.vault_sync.folder_sync import SyncRefused, sync_folder
from config.settings import get_settings

logger = logging.getLogger(__name__)


class VaultSyncNotConfigured(Exception):
    pass


def configured_source(settings=None) -> tuple[str, str] | None:
    """("folder" | "dropbox", description) for what sync reads from, or None when it's off."""

    settings = settings or get_settings()
    if settings.vault_sync_dir:
        return "folder", f"Folder {settings.vault_sync_dir}"
    if settings.dropbox_refresh_token:
        return "dropbox", f"Dropbox {settings.dropbox_root_path or '(app folder)'}"
    return None


def run_vault_sync(
    repository=None, storage_backend=None, vector_store=None, allow_mass_delete: bool = False, process: bool = True,
) -> dict:
    from app.metadata import get_metadata_repository
    from app.storage import get_storage_backend
    from app.vector_store import get_vector_store

    settings = get_settings()
    source = configured_source(settings)
    if source is None:
        raise VaultSyncNotConfigured(
            "Vault sync is off - set VAULT_SYNC_DIR (a Dropbox/Drive-synced folder) or the DROPBOX_* settings."
        )

    repository = repository or get_metadata_repository()
    storage_backend = storage_backend or get_storage_backend()
    vector_store = vector_store or get_vector_store()
    tenant_id = settings.vault_sync_tenant_id
    kind, description = source
    started_at = datetime.now(timezone.utc).isoformat()
    run = {"source": description, "added": 0, "updated": 0, "deleted": 0, "unchanged": 0, "skipped": [], "error": None}

    try:
        if kind == "dropbox":
            mirror_dir = settings.resolve(settings.vault_mirror_dir)
            DropboxMirror(
                settings.dropbox_app_key, settings.dropbox_app_secret, settings.dropbox_refresh_token,
                settings.dropbox_root_path, mirror_dir,
            ).refresh()
            source_dir = mirror_dir
        else:
            source_dir = Path(settings.vault_sync_dir)

        result = sync_folder(
            source_dir, tenant_id, repository, storage_backend, vector_store, allow_mass_delete=allow_mass_delete
        )
        run.update(added=result.added, updated=result.updated, deleted=result.deleted,
                   unchanged=result.unchanged, skipped=result.skipped, status="ok")

        if result.changed and process:
            from app.jobs.processing import run_processing_job

            run["processing"] = run_processing_job(repository, vector_store)
    except SyncRefused as exc:
        run.update(status="refused", error=str(exc))
    except DropboxError as exc:
        run.update(status="failed", error=str(exc))
    except Exception as exc:
        logger.exception("Vault sync failed")
        run.update(status="failed", error=f"Unexpected error: {exc}")

    repository.add_vault_sync_run(tenant_id, {**run, "started_at": started_at})
    return run


def run_vault_sync_job(
    allow_mass_delete: bool = False, repository=None, storage_backend=None, vector_store=None
) -> dict:
    """Entry point for the background worker (RQ) - the API passes its own repository/storage/vector store, like /process."""

    return run_vault_sync(
        repository=repository, storage_backend=storage_backend, vector_store=vector_store,
        allow_mass_delete=allow_mass_delete,
    )

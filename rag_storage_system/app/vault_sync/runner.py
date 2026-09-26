"""
One vault-sync run end to end: refresh the Dropbox mirror (if the Dropbox
API is the source), mirror the source folder into the library
(folder_sync.py), index what changed (app/jobs/processing.py), and record
the outcome (vault_sync_runs) for the Vault page.

Runs in the background worker (POST /admin/vault-sync/run enqueues
run_vault_sync_job) or from scripts/vault_sync.py (once, or on a schedule
with --watch).

Where an organization's library syncs from:
- its own Dropbox, connected by the owner on the Vault page, and the
  folders the owner ticked there (app/api/dropbox_api.py) - each ticked
  folder becomes a library folder, its sub-folders inside it; or
- for VAULT_SYNC_TENANT_ID only, the server settings VAULT_SYNC_DIR or
  DROPBOX_* (the original setup, kept as a fallback).
"""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.security.path_security import sanitize_path_segment
from app.security.secret_box import SecretUnreadable, decrypt
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


def folder_labels(paths: list[str]) -> dict[str, str]:
    """Dropbox folder path -> the library folder it becomes (its own name; "Name (2)" if two share a name)."""

    labels: dict[str, str] = {}
    used: set[str] = set()
    for path in paths:
        base = sanitize_path_segment(path.rstrip("/").rsplit("/", 1)[-1]) or "Dropbox"
        label, n = base, 2
        while label.lower() in used:
            label, n = f"{base} ({n})", n + 1
        used.add(label.lower())
        labels[path] = label
    return labels


def tenant_source(repository, tenant_id: int, settings=None) -> dict | None:
    """{"kind", "description", "connection"?} for what this organization's library syncs from, or None."""

    settings = settings or get_settings()
    connection = repository.get_dropbox_connection(tenant_id)
    if connection and connection["folders"]:
        who = connection.get("account_email") or connection.get("account_name") or "connected account"
        names = ", ".join(folder_labels(connection["folders"]).values())
        return {"kind": "dropbox_connected", "description": f"Dropbox ({who}): {names}", "connection": connection}
    if tenant_id == settings.vault_sync_tenant_id:
        source = configured_source(settings)
        if source:
            return {"kind": source[0], "description": source[1]}
    return None


def synced_tenant_ids(repository, settings=None) -> list[int]:
    """Every organization that currently has a sync source - what scripts/vault_sync.py --watch runs for."""

    settings = settings or get_settings()
    tenants = {c["tenant_id"] for c in repository.list_dropbox_connections() if c["folders"]}
    if configured_source(settings):
        tenants.add(settings.vault_sync_tenant_id)
    return sorted(tenants)


def connected_mirror_dir(settings, tenant_id: int) -> Path:
    # Beside (never inside) the VAULT_MIRROR_DIR the server-settings Dropbox source uses.
    base = settings.resolve(settings.vault_mirror_dir)
    return base.parent / f"{base.name}_connected" / f"tenant-{tenant_id}"


def _refresh_connected_mirror(settings, tenant_id: int, connection: dict) -> Path:
    try:
        refresh_token = decrypt(connection["refresh_token_encrypted"])
    except SecretUnreadable as exc:
        raise DropboxError("The saved Dropbox connection can't be read any more - please reconnect Dropbox.") from exc

    mirror_root = connected_mirror_dir(settings, tenant_id)
    mirror_root.mkdir(parents=True, exist_ok=True)
    labels = folder_labels(connection["folders"])
    for path, label in labels.items():
        DropboxMirror(settings.dropbox_app_key, settings.dropbox_app_secret, refresh_token, path,
                      mirror_root / label).refresh()
    # A folder the owner un-ticked leaves the mirror, so its files leave the library on this run.
    for child in mirror_root.iterdir():
        if child.is_dir() and child.name not in labels.values():
            shutil.rmtree(child)
    return mirror_root


def run_vault_sync(
    repository=None, storage_backend=None, vector_store=None, allow_mass_delete: bool = False, process: bool = True,
    tenant_id: int | None = None,
) -> dict:
    from app.metadata import get_metadata_repository
    from app.storage import get_storage_backend
    from app.vector_store import get_vector_store

    settings = get_settings()
    repository = repository or get_metadata_repository()
    tenant_id = settings.vault_sync_tenant_id if tenant_id is None else tenant_id
    source = tenant_source(repository, tenant_id, settings)
    if source is None:
        raise VaultSyncNotConfigured(
            "Vault sync is off - connect Dropbox and choose folders on the Vault page, "
            "or set VAULT_SYNC_DIR / the DROPBOX_* settings."
        )

    storage_backend = storage_backend or get_storage_backend()
    vector_store = vector_store or get_vector_store()
    kind, description = source["kind"], source["description"]
    started_at = datetime.now(timezone.utc).isoformat()
    run = {"source": description, "added": 0, "updated": 0, "deleted": 0, "unchanged": 0, "skipped": [], "error": None}

    try:
        if kind == "dropbox_connected":
            source_dir = _refresh_connected_mirror(settings, tenant_id, source["connection"])
        elif kind == "dropbox":
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
    allow_mass_delete: bool = False, repository=None, storage_backend=None, vector_store=None,
    tenant_id: int | None = None,
) -> dict:
    """Entry point for the background worker (RQ) - the API passes its own repository/storage/vector store, like /process."""

    return run_vault_sync(
        repository=repository, storage_backend=storage_backend, vector_store=vector_store,
        allow_mass_delete=allow_mass_delete, tenant_id=tenant_id,
    )

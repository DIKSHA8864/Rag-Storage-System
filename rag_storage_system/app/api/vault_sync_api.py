"""
Owner controls for vault sync (app/vault_sync/): see what the library is
synced from and how the last run went, and start a run now. Scheduled
runs come from scripts/vault_sync.py --watch.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import VaultSyncRunInfo, VaultSyncStartResponse, VaultSyncStatusResponse
from app.security.auth import require_owner_role
from app.vault_sync.runner import run_vault_sync_job, tenant_source
from config.settings import get_settings

router = APIRouter(prefix="/admin/vault-sync", tags=["vault-sync"], dependencies=[Depends(require_owner_role)])


def _source(owner: dict) -> dict | None:
    """This organization's sync source: its connected Dropbox folders, or the server-settings fallback."""

    from app.api import storage_api

    return tenant_source(storage_api.metadata_repository, owner["tenant_id"])


@router.get("", response_model=VaultSyncStatusResponse)
def vault_sync_status(owner: dict = Depends(require_owner_role)) -> VaultSyncStatusResponse:
    from app.api import storage_api

    source = _source(owner)
    if source is None:
        return VaultSyncStatusResponse(configured=False, source=None, interval_seconds=None, last_run=None)

    settings = get_settings()
    last = storage_api.metadata_repository.latest_vault_sync_run(owner["tenant_id"])
    return VaultSyncStatusResponse(
        configured=True,
        source=source["description"],
        interval_seconds=settings.vault_sync_interval_seconds,
        last_run=VaultSyncRunInfo(
            id=last["id"], source=last["source"], status=last["status"], added=last["added"], updated=last["updated"],
            deleted=last["deleted"], unchanged=last["unchanged"], skipped=last["skipped"] or [], error=last["error"],
            started_at=str(last["started_at"]), finished_at=str(last["finished_at"]),
        ) if last else None,
    )


@router.post("/run", response_model=VaultSyncStartResponse)
def start_vault_sync(allow_mass_delete: bool = False, owner: dict = Depends(require_owner_role)) -> VaultSyncStartResponse:
    from app.api import storage_api

    if _source(owner) is None:
        raise HTTPException(
            status_code=409, detail="Vault sync isn't set up for your organization - connect Dropbox and choose folders first."
        )

    job = storage_api.get_job_queue().enqueue(
        run_vault_sync_job, allow_mass_delete,
        storage_api.metadata_repository, storage_api.storage_backend, storage_api.get_vector_store(),
        owner["tenant_id"],
    )
    return VaultSyncStartResponse(job_id=job.id, status="queued")

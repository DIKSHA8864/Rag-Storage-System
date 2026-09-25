import { apiRequest } from "./client";
import type { VaultSyncStatusResponse } from "./types";

export async function getVaultSyncStatus(token: string): Promise<VaultSyncStatusResponse> {
  return apiRequest<VaultSyncStatusResponse>("/admin/vault-sync", { token });
}

export async function startVaultSync(token: string, allowMassDelete = false): Promise<{ job_id: string; status: string }> {
  return apiRequest(`/admin/vault-sync/run?allow_mass_delete=${allowMassDelete}`, { method: "POST", token });
}

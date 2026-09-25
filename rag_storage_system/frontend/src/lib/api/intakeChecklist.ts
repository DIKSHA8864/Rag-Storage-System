import { apiRequest } from "./client";
import type { IntakeChecklistItem, IntakeChecklistResponse } from "./types";

export async function getIntakeChecklist(token: string): Promise<IntakeChecklistResponse> {
  return apiRequest<IntakeChecklistResponse>("/admin/intake/checklist", { token });
}

export async function saveIntakeChecklist(token: string, items: IntakeChecklistItem[]): Promise<IntakeChecklistResponse> {
  return apiRequest<IntakeChecklistResponse>("/admin/intake/checklist", { method: "PUT", token, body: { items } });
}

export async function resetIntakeChecklist(token: string): Promise<IntakeChecklistResponse> {
  return apiRequest<IntakeChecklistResponse>("/admin/intake/checklist", { method: "DELETE", token });
}

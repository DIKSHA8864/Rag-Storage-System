import { apiRequest } from "./client";
import type { HandoffInfo, HandoffListResponse } from "./types";

export async function listHandoffs(status: string | null, token: string): Promise<HandoffListResponse> {
  return apiRequest<HandoffListResponse>(`/admin/handoffs${status ? `?status=${status}` : ""}`, { token });
}

export async function claimHandoff(id: number, token: string): Promise<HandoffInfo> {
  return apiRequest<HandoffInfo>(`/admin/handoffs/${id}/claim`, { method: "POST", token });
}

export async function closeHandoff(id: number, note: string, token: string): Promise<HandoffInfo> {
  return apiRequest<HandoffInfo>(`/admin/handoffs/${id}/close`, { method: "POST", body: { note }, token });
}

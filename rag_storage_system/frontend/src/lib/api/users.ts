import { apiRequest } from "./client";
import type { EndUserAccountInfo, EndUserListResponse, InviteEndUsersResponse } from "./types";

export async function listEndUsers(token: string): Promise<EndUserListResponse> {
  return apiRequest<EndUserListResponse>("/admin/users", { token });
}

export async function inviteEndUsers(emails: string[], token: string): Promise<InviteEndUsersResponse> {
  return apiRequest<InviteEndUsersResponse>("/admin/users", { method: "POST", body: { emails }, token });
}

export async function deactivateEndUser(id: number, token: string): Promise<EndUserAccountInfo> {
  return apiRequest<EndUserAccountInfo>(`/admin/users/${id}/deactivate`, { method: "POST", token });
}

export async function reactivateEndUser(id: number, token: string): Promise<EndUserAccountInfo> {
  return apiRequest<EndUserAccountInfo>(`/admin/users/${id}/reactivate`, { method: "POST", token });
}

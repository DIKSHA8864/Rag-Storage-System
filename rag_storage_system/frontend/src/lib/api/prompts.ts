import { apiRequest } from "./client";
import type { PromptVersionCreateRequest, PromptVersionInfo, PromptVersionListResponse } from "./types";

export async function listPromptVersions(name: string, token: string): Promise<PromptVersionListResponse> {
  return apiRequest<PromptVersionListResponse>(`/admin/prompts/${encodeURIComponent(name)}`, { token });
}

export async function createPromptVersion(
  name: string,
  request: PromptVersionCreateRequest,
  token: string
): Promise<PromptVersionInfo> {
  return apiRequest<PromptVersionInfo>(`/admin/prompts/${encodeURIComponent(name)}`, {
    method: "POST",
    body: request,
    token,
  });
}

export async function activatePromptVersion(name: string, version: number, token: string): Promise<PromptVersionInfo> {
  return apiRequest<PromptVersionInfo>(`/admin/prompts/${encodeURIComponent(name)}/activate/${version}`, {
    method: "POST",
    token,
  });
}

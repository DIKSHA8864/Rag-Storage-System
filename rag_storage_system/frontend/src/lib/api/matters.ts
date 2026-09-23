import { apiRequest } from "./client";
import type {
  MatterCreateRequest,
  MatterCreatedResponse,
  MatterInfo,
  MatterIntakeSessionDetailResponse,
  MatterListResponse,
  IntakeSessionListResponse,
  OwnerResearchRequest,
  OwnerResearchResponse,
} from "./types";

export async function listMatters(token: string): Promise<MatterListResponse> {
  return apiRequest<MatterListResponse>("/admin/matters", { token });
}

export async function createMatter(request: MatterCreateRequest, token: string): Promise<MatterCreatedResponse> {
  return apiRequest<MatterCreatedResponse>("/admin/matters", {
    method: "POST",
    body: request,
    token,
  });
}

export async function getMatter(matterId: number, token: string): Promise<MatterInfo> {
  return apiRequest<MatterInfo>(`/admin/matters/${matterId}`, { token });
}

export async function listMatterIntakeSessions(matterId: number, token: string): Promise<IntakeSessionListResponse> {
  return apiRequest<IntakeSessionListResponse>(`/admin/matters/${matterId}/intake-sessions`, { token });
}

export async function getMatterIntakeSessionDetail(
  matterId: number,
  sessionId: number,
  token: string
): Promise<MatterIntakeSessionDetailResponse> {
  return apiRequest<MatterIntakeSessionDetailResponse>(
    `/admin/matters/${matterId}/intake-sessions/${sessionId}`,
    { token }
  );
}

export async function matterResearchAsk(
  matterId: number,
  request: OwnerResearchRequest,
  token: string
): Promise<OwnerResearchResponse> {
  return apiRequest<OwnerResearchResponse>(`/admin/matters/${matterId}/research`, {
    method: "POST",
    body: request,
    token,
  });
}
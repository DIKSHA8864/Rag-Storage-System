import { apiRequest, apiRequestBlob } from "./client";
import type {
  CauseOfActionCreateRequest,
  CauseOfActionInfo,
  CauseOfActionListResponse,
  ComplaintDraftResponse,
  ComplaintGenerateRequest,
  ComplaintListResponse,
} from "./types";

export async function listCausesOfAction(token: string, category?: string): Promise<CauseOfActionListResponse> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  return apiRequest<CauseOfActionListResponse>(`/admin/causes-of-action${query}`, { token });
}

export async function createCauseOfAction(
  request: CauseOfActionCreateRequest,
  token: string
): Promise<CauseOfActionInfo> {
  return apiRequest<CauseOfActionInfo>("/admin/causes-of-action", {
    method: "POST",
    body: request,
    token,
  });
}

export async function generateComplaint(
  sessionId: number,
  request: ComplaintGenerateRequest,
  token: string
): Promise<ComplaintDraftResponse> {
  return apiRequest<ComplaintDraftResponse>(`/admin/intake/sessions/${sessionId}/complaint`, {
    method: "POST",
    body: request,
    token,
  });
}

export async function listSessionComplaints(sessionId: number, token: string): Promise<ComplaintListResponse> {
  return apiRequest<ComplaintListResponse>(`/admin/intake/sessions/${sessionId}/complaints`, { token });
}

export async function downloadComplaint(complaintId: number, token: string): Promise<Blob> {
  return apiRequestBlob(`/admin/complaints/${complaintId}/download`, { token });
}

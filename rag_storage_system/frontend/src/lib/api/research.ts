import { apiRequest, apiRequestBlob } from "./client";
import type {
  OwnerResearchExportRequest,
  OwnerResearchRequest,
  OwnerResearchResponse,
} from "./types";

export async function askResearch(
  request: OwnerResearchRequest,
  token: string
): Promise<OwnerResearchResponse> {
  return apiRequest<OwnerResearchResponse>("/research/ask", {
    method: "POST",
    body: request,
    token,
  });
}

export async function exportResearch(
  request: OwnerResearchExportRequest,
  token: string
): Promise<Blob> {
  return apiRequestBlob("/research/export", {
    method: "POST",
    body: request,
    token,
  });
}
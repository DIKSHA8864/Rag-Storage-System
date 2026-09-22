import { apiRequest } from "./client";
import type { OwnerResearchRequest, OwnerResearchResponse } from "./types";

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
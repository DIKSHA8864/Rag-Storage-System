import { apiRequest } from "./client";
import type { DisclaimerInfo, QueryLogResponse, RetrievalSettingsInfo } from "./types";

export async function getRetrievalSettings(token: string): Promise<RetrievalSettingsInfo> {
  return apiRequest<RetrievalSettingsInfo>("/admin/retrieval-settings", { token });
}

export async function saveRetrievalSettings(
  settings: { top_k: number; score_threshold: number; min_chunks: number },
  token: string
): Promise<RetrievalSettingsInfo> {
  return apiRequest<RetrievalSettingsInfo>("/admin/retrieval-settings", { method: "PUT", body: settings, token });
}

export async function getDisclaimer(token: string): Promise<DisclaimerInfo> {
  return apiRequest<DisclaimerInfo>("/admin/disclaimer", { token });
}

export async function saveDisclaimer(text: string, token: string): Promise<DisclaimerInfo> {
  return apiRequest<DisclaimerInfo>("/admin/disclaimer", { method: "PUT", body: { text }, token });
}

export async function getQueryLog(
  token: string,
  options: { limit: number; offset: number; questionsOnly: boolean }
): Promise<QueryLogResponse> {
  const params = new URLSearchParams({
    limit: String(options.limit),
    offset: String(options.offset),
    questions_only: String(options.questionsOnly),
  });
  return apiRequest<QueryLogResponse>(`/admin/query-log?${params}`, { token });
}

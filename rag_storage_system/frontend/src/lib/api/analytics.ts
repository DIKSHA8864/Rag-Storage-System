import { apiRequest } from "./client";
import type { AnalyticsResponse } from "./types";

export async function getAnalytics(days: number, token: string): Promise<AnalyticsResponse> {
  return apiRequest<AnalyticsResponse>(`/admin/analytics?days=${days}`, { token });
}

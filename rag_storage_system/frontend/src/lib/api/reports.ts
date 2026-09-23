import { apiRequest } from "./client";
import type { ReportReviewInfo, ReportReviewListResponse } from "./types";

export async function listPendingReports(token: string): Promise<ReportReviewListResponse> {
  return apiRequest<ReportReviewListResponse>("/admin/reports/pending", { token });
}

export async function approveReport(reportId: number, token: string): Promise<ReportReviewInfo> {
  return apiRequest<ReportReviewInfo>(`/admin/reports/${reportId}/approve`, {
    method: "POST",
    token,
  });
}

export async function rejectReport(reportId: number, reason: string, token: string): Promise<ReportReviewInfo> {
  return apiRequest<ReportReviewInfo>(`/admin/reports/${reportId}/reject`, {
    method: "POST",
    body: { reason },
    token,
  });
}
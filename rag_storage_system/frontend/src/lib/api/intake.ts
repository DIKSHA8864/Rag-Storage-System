import { endUserRequest, endUserRequestBlob } from "./endUserClient";
import type {
  IntakeSessionCreateRequest,
  IntakeSessionInfo,
  IntakeSessionListResponse,
  InterviewMessageResponse,
  InterviewResumeResponse,
  InterviewStartResponse,
  ReportGenerateRequest,
  ReportInfo,
} from "./types";

export async function listIntakeSessions(endUserToken: string): Promise<IntakeSessionListResponse> {
  return endUserRequest<IntakeSessionListResponse>("/end-user/intake/sessions", { endUserToken });
}

export async function createIntakeSession(
  request: IntakeSessionCreateRequest,
  endUserToken: string
): Promise<IntakeSessionInfo> {
  return endUserRequest<IntakeSessionInfo>("/end-user/intake/sessions", {
    method: "POST",
    body: request,
    endUserToken,
  });
}

export async function startInterview(sessionId: number, endUserToken: string): Promise<InterviewStartResponse> {
  return endUserRequest<InterviewStartResponse>(`/end-user/intake/sessions/${sessionId}/interview/start`, {
    method: "POST",
    endUserToken,
  });
}

export async function sendInterviewMessage(
  sessionId: number,
  message: string,
  endUserToken: string
): Promise<InterviewMessageResponse> {
  return endUserRequest<InterviewMessageResponse>(`/end-user/intake/sessions/${sessionId}/interview/message`, {
    method: "POST",
    body: { message },
    endUserToken,
  });
}

export async function resumeInterview(sessionId: number, endUserToken: string): Promise<InterviewResumeResponse> {
  return endUserRequest<InterviewResumeResponse>(`/end-user/intake/sessions/${sessionId}/interview`, { endUserToken });
}

export async function generateIntakeReport(
  sessionId: number,
  request: ReportGenerateRequest,
  endUserToken: string
): Promise<ReportInfo> {
  return endUserRequest<ReportInfo>(`/end-user/intake/sessions/${sessionId}/report`, {
    method: "POST",
    body: request,
    endUserToken,
  });
}

export async function downloadIntakeReport(reportId: number, endUserToken: string): Promise<Blob> {
  return endUserRequestBlob(`/end-user/intake/reports/${reportId}/download`, { endUserToken });
}
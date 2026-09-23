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

export async function listIntakeSessions(endUserKey: string): Promise<IntakeSessionListResponse> {
  return endUserRequest<IntakeSessionListResponse>("/end-user/intake/sessions", { endUserKey });
}

export async function createIntakeSession(
  request: IntakeSessionCreateRequest,
  endUserKey: string
): Promise<IntakeSessionInfo> {
  return endUserRequest<IntakeSessionInfo>("/end-user/intake/sessions", {
    method: "POST",
    body: request,
    endUserKey,
  });
}

export async function startInterview(sessionId: number, endUserKey: string): Promise<InterviewStartResponse> {
  return endUserRequest<InterviewStartResponse>(`/end-user/intake/sessions/${sessionId}/interview/start`, {
    method: "POST",
    endUserKey,
  });
}

export async function sendInterviewMessage(
  sessionId: number,
  message: string,
  endUserKey: string
): Promise<InterviewMessageResponse> {
  return endUserRequest<InterviewMessageResponse>(`/end-user/intake/sessions/${sessionId}/interview/message`, {
    method: "POST",
    body: { message },
    endUserKey,
  });
}

export async function resumeInterview(sessionId: number, endUserKey: string): Promise<InterviewResumeResponse> {
  return endUserRequest<InterviewResumeResponse>(`/end-user/intake/sessions/${sessionId}/interview`, { endUserKey });
}

export async function generateIntakeReport(
  sessionId: number,
  request: ReportGenerateRequest,
  endUserKey: string
): Promise<ReportInfo> {
  return endUserRequest<ReportInfo>(`/end-user/intake/sessions/${sessionId}/report`, {
    method: "POST",
    body: request,
    endUserKey,
  });
}

export async function downloadIntakeReport(reportId: number, endUserKey: string): Promise<Blob> {
  return endUserRequestBlob(`/end-user/intake/reports/${reportId}/download`, { endUserKey });
}
import { endUserRequest } from "./endUserClient";
import type {
  IntakeSessionCreateRequest,
  IntakeSessionInfo,
  IntakeSessionListResponse,
  InterviewMessageResponse,
  InterviewResumeResponse,
  InterviewStartResponse,
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
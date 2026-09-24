import { API_BASE_URL, endUserRequest, endUserRequestBlob } from "./endUserClient";
import { ApiError } from "./client";
import type {
  IntakeSessionCreateRequest,
  IntakeSessionInfo,
  IntakeSessionListResponse,
  IntakeUploadListResponse,
  InterviewMessageResponse,
  InterviewResumeResponse,
  InterviewStartResponse,
  ReportGenerateRequest,
  ReportInfo,
  UploadedInputQueuedResponse,
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
export async function listIntakeUploads(sessionId: number, endUserToken: string): Promise<IntakeUploadListResponse> {
  return endUserRequest<IntakeUploadListResponse>(`/end-user/intake/sessions/${sessionId}/uploads`, { endUserToken });
}

/**
 * POST /end-user/intake/sessions/{id}/uploads as multipart form data.
 * Uses XMLHttpRequest rather than fetch() only because fetch() can't
 * report upload progress - which matters for a large video.
 */
export function uploadIntakeFile(
  sessionId: number,
  file: File,
  endUserToken: string,
  onProgress: (percent: number) => void
): Promise<UploadedInputQueuedResponse> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE_URL}/end-user/intake/sessions/${sessionId}/uploads`);
    request.setRequestHeader("Authorization", `Bearer ${endUserToken}`);

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    request.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        // Not JSON - handled below.
      }

      if (request.status >= 200 && request.status < 300) {
        resolve(body as UploadedInputQueuedResponse);
        return;
      }

      const detail = (body as { detail?: unknown } | null)?.detail;
      reject(
        new ApiError(
          request.status,
          typeof detail === "string" ? detail : `Upload failed with status ${request.status}.`
        )
      );
    };

    request.onerror = () => reject(new ApiError(0, "Could not reach the server. Check your connection and try again."));

    const formData = new FormData();
    formData.append("file", file);
    request.send(formData);
  });
}

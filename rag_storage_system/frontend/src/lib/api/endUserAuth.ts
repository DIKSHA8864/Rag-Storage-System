import { endUserFetch, endUserRequest } from "./endUserClient";
import { readSseStream } from "./sse";
import type { EndUserQuerySource, EndUserSessionResponse, GenericMessageResponse } from "./types";

export async function requestSignupCode(email: string): Promise<GenericMessageResponse> {
  return endUserRequest<GenericMessageResponse>("/end-user/auth/signup/request-code", {
    method: "POST",
    body: { email },
    endUserToken: null,
  });
}

export async function completeSignup(email: string, code: string, password: string): Promise<EndUserSessionResponse> {
  return endUserRequest<EndUserSessionResponse>("/end-user/auth/signup/complete", {
    method: "POST",
    body: { email, code, password },
    endUserToken: null,
  });
}

export async function endUserLogin(email: string, password: string): Promise<EndUserSessionResponse> {
  return endUserRequest<EndUserSessionResponse>("/end-user/auth/login", {
    method: "POST",
    body: { email, password },
    endUserToken: null,
  });
}

export async function requestPasswordResetCode(email: string): Promise<GenericMessageResponse> {
  return endUserRequest<GenericMessageResponse>("/end-user/auth/password-reset/request-code", {
    method: "POST",
    body: { email },
    endUserToken: null,
  });
}

export async function completePasswordReset(
  email: string,
  code: string,
  newPassword: string
): Promise<GenericMessageResponse> {
  return endUserRequest<GenericMessageResponse>("/end-user/auth/password-reset/complete", {
    method: "POST",
    body: { email, code, new_password: newPassword },
    endUserToken: null,
  });
}

export async function fetchEndUserMe(endUserToken: string): Promise<{ id: number; email: string; status: string }> {
  return endUserRequest("/end-user/auth/me", { endUserToken });
}

export interface AskStreamHandlers {
  onSources: (sources: EndUserQuerySource[]) => void;
  onAnswerChunk: (text: string) => void;
  onError: (detail: string) => void;
}

/**
 * POST /end-user/query/stream - reads the Server-Sent Events stream
 * (sources first, then answer chunks, then done) as it arrives, so
 * the answer appears gradually. Sources are locked by the backend
 * before any answer text is generated (citation lock).
 */
export async function askStream(
  query: string,
  endUserToken: string,
  handlers: AskStreamHandlers,
  threadId: number | null = null
): Promise<void> {
  const response = await endUserFetch(
    "/end-user/query/stream",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // With a thread_id the backend saves this question and its answer to that (the caller's own) thread.
      body: JSON.stringify(threadId === null ? { query } : { query, thread_id: threadId }),
    },
    endUserToken
  );

  await readSseStream(response, (eventType, data) => {
    if (eventType === "sources") handlers.onSources((data.sources as EndUserQuerySource[]) ?? []);
    else if (eventType === "answer_chunk") handlers.onAnswerChunk((data.text as string) ?? "");
    else if (eventType === "error") handlers.onError((data.detail as string) ?? "Something went wrong.");
  });
}


// ---------------------------------------------------------------------
// The signed-in user's saved questions (app/api/end_user_api.py threads):
// always the caller's own matter - the backend 404s anyone else's.
// ---------------------------------------------------------------------

export interface EndUserThreadInfo {
  id: number;
  matter_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface EndUserThreadMessage {
  id: number;
  thread_id: number;
  role: "user" | "assistant";
  content: string;
  sources: EndUserQuerySource[];
  created_at: string;
}

export async function createEndUserThread(title: string, endUserToken: string): Promise<EndUserThreadInfo> {
  return endUserRequest<EndUserThreadInfo>("/end-user/threads", { method: "POST", body: { title }, endUserToken });
}

export async function listEndUserThreads(endUserToken: string): Promise<{ threads: EndUserThreadInfo[] }> {
  return endUserRequest<{ threads: EndUserThreadInfo[] }>("/end-user/threads", { endUserToken });
}

export async function getEndUserThreadMessages(
  threadId: number,
  endUserToken: string
): Promise<{ thread_id: number; messages: EndUserThreadMessage[] }> {
  return endUserRequest(`/end-user/threads/${threadId}/messages`, { endUserToken });
}

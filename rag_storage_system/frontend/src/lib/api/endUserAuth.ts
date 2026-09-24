import { endUserFetch, endUserRequest } from "./endUserClient";
import { ApiError } from "./client";
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
export async function askStream(query: string, endUserToken: string, handlers: AskStreamHandlers): Promise<void> {
  const response = await endUserFetch(
    "/end-user/query/stream",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    },
    endUserToken
  );

  if (!response.body) {
    throw new ApiError(0, "The server returned an empty response.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;

  const handleEvent = (rawEvent: string) => {
    const lines = rawEvent.split("\n");
    const eventLine = lines.find((l) => l.startsWith("event: "));
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (!eventLine || !dataLine) return;

    const eventType = eventLine.slice("event: ".length);
    const data = JSON.parse(dataLine.slice("data: ".length));

    if (eventType === "sources") handlers.onSources(data.sources ?? []);
    else if (eventType === "answer_chunk") handlers.onAnswerChunk(data.text ?? "");
    else if (eventType === "error") handlers.onError(data.detail ?? "Something went wrong.");
    else if (eventType === "done") sawDone = true;
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    let separatorIndex = buffer.indexOf("\n\n");
    while (separatorIndex !== -1) {
      handleEvent(buffer.slice(0, separatorIndex));
      buffer = buffer.slice(separatorIndex + 2);
      separatorIndex = buffer.indexOf("\n\n");
    }
  }

  if (buffer.trim()) handleEvent(buffer);

  // A stream that stops without "done" was cut off by a server-side
  // failure - never let that read as an honest "no authority found".
  if (!sawDone) {
    throw new ApiError(0, "The answer was interrupted. Please try again.");
  }
}


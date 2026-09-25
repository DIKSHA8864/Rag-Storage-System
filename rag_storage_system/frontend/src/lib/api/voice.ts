import { endUserFetch, endUserRequest } from "./endUserClient";
import type { HandoffCreateRequest, HandoffInfo } from "./types";

export async function getVoiceCapabilities(endUserToken: string): Promise<{ speech_to_text: boolean }> {
  return endUserRequest<{ speech_to_text: boolean }>("/end-user/intake/voice", { endUserToken });
}

/** Spoken answer -> text for the client to check. Nothing is recorded until they send it. */
export async function transcribeAnswer(sessionId: number, recording: Blob, endUserToken: string): Promise<string> {
  const form = new FormData();
  const extension = recording.type.includes("ogg") ? "ogg" : recording.type.includes("mp4") ? "m4a" : "webm";
  form.append("file", recording, `answer.${extension}`);
  const response = await endUserFetch(
    `/end-user/intake/sessions/${sessionId}/interview/transcribe`,
    { method: "POST", body: form },
    endUserToken
  );
  return ((await response.json()) as { text: string }).text;
}

export async function getMyHandoff(endUserToken: string): Promise<HandoffInfo | null> {
  return endUserRequest<HandoffInfo | null>("/end-user/handoff", { endUserToken });
}

export async function requestHandoff(request: HandoffCreateRequest, endUserToken: string): Promise<HandoffInfo> {
  return endUserRequest<HandoffInfo>("/end-user/handoff", { method: "POST", body: request, endUserToken });
}

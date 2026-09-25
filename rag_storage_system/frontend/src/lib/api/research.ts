import { apiRequest, apiRequestBlob, apiStreamRequest } from "./client";
import { readSseStream } from "./sse";
import type {
  OwnerResearchExportRequest,
  OwnerResearchRequest,
  OwnerResearchResponse,
  OwnerResearchSource,
  ResearchThreadDetailResponse,
  ResearchThreadInfo,
} from "./types";

export async function askResearch(
  request: OwnerResearchRequest,
  token: string
): Promise<OwnerResearchResponse> {
  return apiRequest<OwnerResearchResponse>("/research/ask", {
    method: "POST",
    body: request,
    token,
  });
}

export async function exportResearch(
  request: OwnerResearchExportRequest,
  token: string
): Promise<Blob> {
  return apiRequestBlob("/research/export", {
    method: "POST",
    body: request,
    token,
  });
}
// ---------------------------------------------------------------------
// Saved research threads + streamed answers
// ---------------------------------------------------------------------

export async function listResearchThreads(token: string): Promise<ResearchThreadInfo[]> {
  return (await apiRequest<{ threads: ResearchThreadInfo[] }>("/research/threads", { token })).threads;
}

export async function getResearchThread(threadId: number, token: string): Promise<ResearchThreadDetailResponse> {
  return apiRequest<ResearchThreadDetailResponse>(`/research/threads/${threadId}`, { token });
}

export async function renameResearchThread(threadId: number, title: string, token: string): Promise<ResearchThreadInfo> {
  return apiRequest<ResearchThreadInfo>(`/research/threads/${threadId}`, { method: "PATCH", body: { title }, token });
}

export async function deleteResearchThread(threadId: number, token: string): Promise<void> {
  await apiRequest(`/research/threads/${threadId}`, { method: "DELETE", token });
}

export async function exportResearchThread(threadId: number, format: "docx" | "pdf", token: string): Promise<Blob> {
  return apiRequestBlob(`/research/threads/${threadId}/export`, { method: "POST", body: { format }, token });
}

export interface ResearchStreamHandlers {
  onThread: (thread: { thread_id: number; title: string }) => void;
  onSources: (sources: OwnerResearchSource[]) => void;
  onAnswerChunk: (text: string) => void;
  onError: (detail: string) => void;
}

/** POST /research/ask/stream - the answer arrives gradually; it's saved to the thread once complete. */
export async function askResearchStream(
  body: { query: string; thread_id?: number },
  token: string,
  handlers: ResearchStreamHandlers
): Promise<void> {
  const response = await apiStreamRequest("/research/ask/stream", body, token);
  await readSseStream(response, (eventType, data) => {
    if (eventType === "thread") handlers.onThread(data as { thread_id: number; title: string });
    else if (eventType === "sources") handlers.onSources((data.sources as OwnerResearchSource[]) ?? []);
    else if (eventType === "answer_chunk") handlers.onAnswerChunk((data.text as string) ?? "");
    else if (eventType === "error") handlers.onError((data.detail as string) ?? "Something went wrong.");
  });
}

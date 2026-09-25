// The one place that knows how to reach the FastAPI backend - every
// other API module (auth.ts, research.ts, documents.ts, ...) calls
// through this, never fetch() directly, so the base URL, auth header,
// and error shape are handled in exactly one place.

import type { ApiErrorBody } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!API_BASE_URL) {
  // Fails loudly at build/runtime rather than silently calling a
  // relative path that happens to 404 - a misconfigured environment
  // should never look like a working one.
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is not set. Add it to frontend/.env.local (see .env.local.example)."
  );
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
}

async function fetchOrThrow(path: string, init: RequestInit, token?: string | null): Promise<Response> {
  const headers = new Headers(init.headers);

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;

    try {
      const errorBody = (await response.json()) as ApiErrorBody;
      if (errorBody.detail) {
        detail = errorBody.detail;
      }
    } catch {
      // Response wasn't JSON (or had no body) - keep the generic message.
    }

    throw new ApiError(response.status, detail);
  }

  return response;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token } = options;

  const response = await fetchOrThrow(
    path,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    token
  );

  // 204 No Content or an empty body - nothing to parse.
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function apiRequestBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  const { method = "GET", body, token } = options;

  const response = await fetchOrThrow(
    path,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    token
  );

  return response.blob();
}

// No Content-Type header here on purpose - the browser sets
// multipart/form-data with the correct boundary itself when the body
// is a FormData instance, and setting it manually breaks that.
export async function apiRequestFormData<T>(
  path: string,
  formData: FormData,
  options: { method?: "POST" | "PUT"; token?: string | null } = {}
): Promise<T> {
  const { method = "POST", token } = options;

  const response = await fetchOrThrow(path, { method, body: formData }, token);

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** POST a JSON body and hand back the raw Response - for streamed (Server-Sent Events) replies. */
export async function apiStreamRequest(path: string, body: unknown, token?: string | null): Promise<Response> {
  return fetchOrThrow(
    path,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    token
  );
}

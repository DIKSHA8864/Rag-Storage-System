// The one place that knows how to reach the FastAPI backend - every
// other API module (auth.ts, research.ts, ...) calls through this,
// never fetch() directly, so the base URL, auth header, and error
// shape are handled in exactly one place.

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

async function fetchOrThrow(path: string, options: RequestOptions): Promise<Response> {
  const { method = "GET", body, token } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
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
  const response = await fetchOrThrow(path, options);

  // 204 No Content or an empty body - nothing to parse.
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function apiRequestBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  const response = await fetchOrThrow(path, options);
  return response.blob();
}
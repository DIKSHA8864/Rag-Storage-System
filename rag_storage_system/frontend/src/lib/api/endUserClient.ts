// Mirrors lib/api/client.ts's fetch/error-handling shape, but for the
// End User / Client Intake surface, which authenticates with the raw
// X-End-User-Key header (app/security/auth.py's require_end_user_key)
// instead of the Owner's JWT Bearer token - two genuinely separate
// credential types, kept in separate client modules on purpose so an
// Owner token and a Client access code can never be mixed up.

import { ApiError } from "./client";
import type { ApiErrorBody } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!API_BASE_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is not set. Add it to frontend/.env.local (see .env.local.example)."
  );
}

interface EndUserRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  endUserKey: string;
}

async function fetchOrThrow(path: string, init: RequestInit, endUserKey: string): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-End-User-Key", endUserKey);

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

export async function endUserRequest<T>(path: string, options: EndUserRequestOptions): Promise<T> {
  const { method = "GET", body, endUserKey } = options;

  const response = await fetchOrThrow(
    path,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    endUserKey
  );

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function endUserRequestBlob(
  path: string,
  options: { method?: "GET" | "POST"; endUserKey: string }
): Promise<Blob> {
  const { method = "GET", endUserKey } = options;
  const response = await fetchOrThrow(path, { method }, endUserKey);
  return response.blob();
}
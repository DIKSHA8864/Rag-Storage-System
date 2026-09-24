// Mirrors lib/api/client.ts's fetch/error-handling shape, but for the
// End User portal, which authenticates with an end-user SESSION token
// (POST /end-user/auth/login - app/security/end_user_accounts.py)
// instead of the Owner's token. Kept in a separate module on purpose
// so an Owner session and an end-user session can never be mixed up:
// the backend rejects an Owner token on end-user endpoints and an
// end-user token on Owner endpoints either way.

import { ApiError } from "./client";
import type { ApiErrorBody } from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!API_BASE_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is not set. Add it to frontend/.env.local (see .env.local.example)."
  );
}

interface EndUserRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  endUserToken: string | null;
}

export async function readErrorDetail(response: Response): Promise<string> {
  try {
    const errorBody = (await response.json()) as ApiErrorBody;
    if (errorBody.detail) {
      return typeof errorBody.detail === "string" ? errorBody.detail : "Please check the details you entered.";
    }
  } catch {
    // Response wasn't JSON (or had no body) - fall through to the generic message.
  }
  return `Request failed with status ${response.status}.`;
}

export async function endUserFetch(path: string, init: RequestInit, endUserToken: string | null): Promise<Response> {
  const headers = new Headers(init.headers);
  if (endUserToken) {
    headers.set("Authorization", `Bearer ${endUserToken}`);
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }

  return response;
}

export async function endUserRequest<T>(path: string, options: EndUserRequestOptions): Promise<T> {
  const { method = "GET", body, endUserToken } = options;

  const response = await endUserFetch(
    path,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    endUserToken
  );

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function endUserRequestBlob(
  path: string,
  options: { method?: "GET" | "POST"; endUserToken: string }
): Promise<Blob> {
  const { method = "GET", endUserToken } = options;
  const response = await endUserFetch(path, { method }, endUserToken);
  return response.blob();
}

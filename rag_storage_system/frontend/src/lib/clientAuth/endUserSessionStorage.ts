// The only file that touches localStorage for the end-user portal
// session - mirrors lib/auth/token-storage.ts (the Owner's session),
// under separate keys so the two sessions never collide.

import { isEndUserToken } from "../auth/tokenClaims";

const TOKEN_KEY = "ashilegal_end_user_session_token";
const EXPIRES_AT_KEY = "ashilegal_end_user_session_expires_at";
const EMAIL_KEY = "ashilegal_end_user_session_email";

export interface StoredEndUserSession {
  token: string;
  email: string;
  expiresAt: number; // epoch ms
}

export function saveEndUserSession(token: string, email: string, expiresInSeconds: number): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(EMAIL_KEY, email);
    localStorage.setItem(EXPIRES_AT_KEY, String(Date.now() + expiresInSeconds * 1000));
  } catch {
    // Storage unavailable - the session simply won't persist across reloads.
  }
}

export function loadEndUserSession(): StoredEndUserSession | null {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const email = localStorage.getItem(EMAIL_KEY);
    const expiresAt = Number(localStorage.getItem(EXPIRES_AT_KEY));

    if (!token || !email || Number.isNaN(expiresAt) || Date.now() >= expiresAt || !isEndUserToken(token)) {
      clearEndUserSession();
      return null;
    }

    return { token, email, expiresAt };
  } catch {
    return null;
  }
}

export function clearEndUserSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
    localStorage.removeItem(EXPIRES_AT_KEY);
  } catch {
    // Nothing to do - already effectively logged out.
  }
}

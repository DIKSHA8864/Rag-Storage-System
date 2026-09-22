// The only file that touches localStorage directly - everything else
// goes through AuthContext. Wrapped in try/catch: localStorage throws
// in some environments (private browsing, SSR) and a storage failure
// must never crash the app, only mean "not logged in."

const TOKEN_KEY = "ashilegal_owner_access_token";
const EXPIRES_AT_KEY = "ashilegal_owner_token_expires_at";

export interface StoredSession {
  token: string;
  expiresAt: number; // epoch ms
}

export function saveSession(token: string, expiresInSeconds: number): void {
  try {
    const expiresAt = Date.now() + expiresInSeconds * 1000;
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(EXPIRES_AT_KEY, String(expiresAt));
  } catch {
    // Storage unavailable - the session simply won't persist across reloads.
  }
}

export function loadSession(): StoredSession | null {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const expiresAtRaw = localStorage.getItem(EXPIRES_AT_KEY);

    if (!token || !expiresAtRaw) {
      return null;
    }

    const expiresAt = Number(expiresAtRaw);

    if (Number.isNaN(expiresAt) || Date.now() >= expiresAt) {
      clearSession();
      return null;
    }

    return { token, expiresAt };
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EXPIRES_AT_KEY);
  } catch {
    // Nothing to do - already effectively logged out.
  }
}
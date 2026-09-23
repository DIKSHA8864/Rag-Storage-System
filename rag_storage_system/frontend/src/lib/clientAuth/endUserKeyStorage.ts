// The only file that touches localStorage directly for the client-
// facing intake flow - mirrors lib/auth/token-storage.ts's pattern,
// but for the raw X-End-User-Key (a permanent credential the firm
// issues per Matter - no expiry to track, unlike the Owner's JWT).

const END_USER_KEY_STORAGE_KEY = "ashilegal_end_user_key";

export function saveEndUserKey(key: string): void {
  try {
    localStorage.setItem(END_USER_KEY_STORAGE_KEY, key);
  } catch {
    // Storage unavailable - the session simply won't persist across reloads.
  }
}

export function loadEndUserKey(): string | null {
  try {
    return localStorage.getItem(END_USER_KEY_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearEndUserKey(): void {
  try {
    localStorage.removeItem(END_USER_KEY_STORAGE_KEY);
  } catch {
    // Nothing to do - already effectively logged out.
  }
}
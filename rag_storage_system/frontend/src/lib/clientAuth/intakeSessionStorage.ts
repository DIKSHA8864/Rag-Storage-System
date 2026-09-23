// Persists which real intake session (app/api/schemas.py's
// IntakeSessionInfo.id) this browser is mid-interview on, so a client
// who closes the tab and comes back resumes instead of starting over.

const INTAKE_SESSION_STORAGE_KEY = "ashilegal_intake_session_id";

export function saveIntakeSessionId(id: number): void {
  try {
    localStorage.setItem(INTAKE_SESSION_STORAGE_KEY, String(id));
  } catch {
    // Ignore - the client will just be asked to start a new session next time.
  }
}

export function loadIntakeSessionId(): number | null {
  try {
    const raw = localStorage.getItem(INTAKE_SESSION_STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export function clearIntakeSessionId(): void {
  try {
    localStorage.removeItem(INTAKE_SESSION_STORAGE_KEY);
  } catch {
    // Ignore.
  }
}
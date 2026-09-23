// Persists which real report (app/api/schemas.py's ReportInfo.id)
// this browser generated for its intake session, so the client isn't
// tempted to re-generate (each generate call creates a NEW report row
// server-side - this is what stops that from happening by accident).

const INTAKE_REPORT_STORAGE_KEY = "ashilegal_intake_report_id";

export function saveIntakeReportId(id: number): void {
  try {
    localStorage.setItem(INTAKE_REPORT_STORAGE_KEY, String(id));
  } catch {
    // Ignore - the client can just generate again if needed.
  }
}

export function loadIntakeReportId(): number | null {
  try {
    const raw = localStorage.getItem(INTAKE_REPORT_STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export function clearIntakeReportId(): void {
  try {
    localStorage.removeItem(INTAKE_REPORT_STORAGE_KEY);
  } catch {
    // Ignore.
  }
}
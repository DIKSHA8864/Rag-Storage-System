// Who this browser is signed in as: firm staff (Owner/Admin console) or an
// end user (client portal) - never both at once. The API already refuses the
// wrong kind of token on every endpoint; this keeps the browser consistent
// with that, so a client who signs in on a computer where an admin was signed
// in never sees the admin console (and the other way round).

import { clearSession, loadSession } from "./auth/token-storage";
import { clearEndUserSession, loadEndUserSession } from "./clientAuth/endUserSessionStorage";
import { clearIntakeReportId } from "./clientAuth/intakeReportStorage";
import { clearIntakeSessionId } from "./clientAuth/intakeSessionStorage";

export type BrowserIdentity = "staff" | "end_user";

const ACTIVE_KEY = "ashilegal_active_identity";
export const SESSION_CHANGED_EVENT = "ashilegal:session-changed";

/** Where each kind of user lands - and where they're sent if they open the other side's pages. */
export const STAFF_HOME = "/dashboard";
export const END_USER_HOME = "/ask";

/** Pages that belong to the end-user portal (the admin console's chrome never renders on them). */
export const END_USER_PATH_PREFIXES = ["/portal", "/ask", "/intake"];

export function isEndUserPath(pathname: string | null): boolean {
  return !!pathname && END_USER_PATH_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function announceSessionChange(): void {
  try {
    window.dispatchEvent(new Event(SESSION_CHANGED_EVENT));
  } catch {
    // No window (SSR) - nothing is listening anyway.
  }
}

function clearEndUserData(): void {
  clearEndUserSession();
  // The in-progress intake/report belong to that end user - never carry them over.
  clearIntakeSessionId();
  clearIntakeReportId();
}

/** Called right after a successful sign-in: this identity is now the browser's only one. */
export function markActiveIdentity(identity: BrowserIdentity): void {
  try {
    localStorage.setItem(ACTIVE_KEY, identity);
  } catch {
    // Storage unavailable - sessions don't persist either, so there's nothing to reconcile.
  }
  if (identity === "staff") {
    clearEndUserData();
  } else {
    clearSession();
  }
  announceSessionChange();
}

/**
 * Run before reading a saved session. If both kinds are saved (e.g. from
 * before this rule existed), keep only the one signed in last; if that's
 * unknown, sign both out rather than guess who is at the keyboard.
 */
export function reconcileSessions(): void {
  const staff = loadSession();
  const endUser = loadEndUserSession();
  if (!staff || !endUser) {
    return;
  }
  let active: string | null = null;
  try {
    active = localStorage.getItem(ACTIVE_KEY);
  } catch {
    active = null;
  }
  if (active === "staff") {
    clearEndUserData();
  } else if (active === "end_user") {
    clearSession();
  } else {
    clearSession();
    clearEndUserData();
  }
}

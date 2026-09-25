// Reads the role out of a saved session token so the browser only treats a
// token as what it really is. This is for routing only - the API verifies
// every token's signature and role itself (app/security/auth.py) and refuses
// the wrong kind on every endpoint.

export const STAFF_ROLES = ["owner", "attorney", "paralegal"] as const;
export const END_USER_ROLE = "end_user";

interface TokenClaims {
  role?: string;
  exp?: number;
}

export function readTokenClaims(token: string): TokenClaims | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(payload.length / 4) * 4, "=");
    return JSON.parse(atob(base64)) as TokenClaims;
  } catch {
    return null;
  }
}

function hasRole(token: string, roles: readonly string[]): boolean {
  const claims = readTokenClaims(token);
  if (!claims?.role || !roles.includes(claims.role)) return false;
  return !claims.exp || claims.exp * 1000 > Date.now();
}

export function isStaffToken(token: string): boolean {
  return hasRole(token, STAFF_ROLES);
}

export function isEndUserToken(token: string): boolean {
  return hasRole(token, [END_USER_ROLE]);
}

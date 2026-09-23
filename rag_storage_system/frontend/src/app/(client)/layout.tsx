import type { ReactNode } from "react";

import { EndUserAuthProvider } from "@/lib/clientAuth/EndUserAuthContext";

/**
 * Every page under app/(client)/ is the PUBLIC, client-facing surface
 * - authenticated with the firm-issued X-End-User-Key
 * (app/security/auth.py's require_end_user_key), a completely
 * separate credential from the Owner's JWT used under
 * app/(protected)/. Never nested inside ProtectedRoute - a client
 * must never need an Owner login to reach their own intake.
 */
export default function ClientLayout({ children }: { children: ReactNode }) {
  return <EndUserAuthProvider>{children}</EndUserAuthProvider>;
}
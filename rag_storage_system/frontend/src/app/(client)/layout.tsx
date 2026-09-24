import type { ReactNode } from "react";

import { EndUserAuthProvider } from "@/lib/clientAuth/EndUserAuthContext";
import { PortalHeader } from "@/components/portal/PortalHeader";

/**
 * Every page under app/(client)/ is the end-user portal - signed in
 * with an individual end-user account (POST /end-user/auth/login,
 * app/security/end_user_accounts.py), a completely separate session
 * from the Owner/Admin's under app/(protected)/.
 */
export default function ClientLayout({ children }: { children: ReactNode }) {
  return (
    <EndUserAuthProvider>
      <PortalHeader />
      {children}
    </EndUserAuthProvider>
  );
}

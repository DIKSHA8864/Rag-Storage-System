"use client";

import { useRouter } from "next/navigation";

import { NavLink } from "@/components/layout/NavLink";
import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";

/** The client portal's top bar - only ever Ask and My Intake; no library/admin pages exist on this side. */
export function PortalHeader() {
  const { isAuthenticated, email, logout } = useEndUserAuth();
  const router = useRouter();

  function handleLogout() {
    logout();
    router.push("/portal/login");
  }

  return (
    <header className="p-header">
      <div className="p-header-inner">
        <div className="p-brand">
          <b>AshiLegal</b>
          <span>Client portal</span>
        </div>

        {isAuthenticated && (
          <>
            <nav className="p-tabs" aria-label="Portal">
              <NavLink href="/ask">Ask</NavLink>
              <NavLink href="/intake">My Intake</NavLink>
            </nav>
            <div className="p-account">
              <span>{email}</span>
              <button type="button" onClick={handleLogout}>
                Sign out
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}

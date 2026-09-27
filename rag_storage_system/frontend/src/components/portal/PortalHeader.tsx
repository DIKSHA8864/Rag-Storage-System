"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { NavLink } from "@/components/layout/NavLink";
import { Icon } from "@/components/ui/Icon";
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
        <Link href={isAuthenticated ? "/ask" : "/"} className="p-brand" aria-label="AshiLegal client portal home">
          <span className="p-logo" aria-hidden>
            A
          </span>
          <span>
            <b>AshiLegal</b>
            <small>Client portal</small>
          </span>
        </Link>

        {isAuthenticated && (
          <>
            <nav className="p-tabs" aria-label="Portal">
              <NavLink href="/ask" icon="ask">
                Ask
              </NavLink>
              <NavLink href="/intake" icon="intake">
                My Intake
              </NavLink>
            </nav>
            <div className="p-account">
              <span className="p-avatar" aria-hidden>
                {(email?.[0] ?? "?").toUpperCase()}
              </span>
              <span className="p-account-email">{email}</span>
              <button type="button" onClick={handleLogout}>
                <Icon name="logout" size={15} /> Sign out
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}

"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { NavLink } from "@/components/layout/NavLink";
import { readTokenClaims } from "@/lib/auth/tokenClaims";
import { useAuth } from "@/lib/auth/useAuth";
import { isEndUserPath } from "@/lib/sessionIdentity";

import "./console.css";

/** The staff console's sections, grouped the way the firm uses them. */
const NAV_GROUPS: { label: string; links: { href: string; label: string }[] }[] = [
  {
    label: "Overview",
    links: [
      { href: "/dashboard", label: "Dashboard" },
      { href: "/analytics", label: "Analytics" },
      { href: "/activity", label: "Activity" },
    ],
  },
  {
    label: "Library",
    links: [
      { href: "/vault", label: "Vault" },
      { href: "/research", label: "Research" },
    ],
  },
  {
    label: "Clients",
    links: [
      { href: "/matters", label: "Matters" },
      { href: "/requests", label: "Requests" },
      { href: "/users", label: "Users" },
    ],
  },
  {
    label: "Setup",
    links: [
      { href: "/intake-checklist", label: "Intake questions" },
      { href: "/prompts", label: "Prompts" },
      { href: "/settings", label: "Settings" },
      { href: "/billing", label: "Billing" },
    ],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, token, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  // The client portal draws its own header and page (app/(client)/layout.tsx).
  if (isEndUserPath(pathname)) {
    return <>{children}</>;
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  // Session still being read from storage: no chrome yet, so nothing flickers.
  if (isLoading) {
    return (
      <div className="console">
        <main>{children}</main>
      </div>
    );
  }

  // Signed out (administrator sign-in, welcome page): no console navigation.
  if (!isAuthenticated) {
    return (
      <div className="console">
        <header className="c-topbar">
          <div className="c-brand">
            <b>AshiLegal</b>
            <span>Firm console</span>
          </div>
        </header>
        <main style={{ padding: "1.5rem 1rem" }}>{children}</main>
      </div>
    );
  }

  const claims = token ? readTokenClaims(token) : null;

  return (
    <div className="console">
      <div className="c-shell">
        <aside className="c-side">
          <div className="c-brand">
            <b>AshiLegal</b>
            <span>Firm console</span>
          </div>
          <nav className="c-nav" aria-label="Console">
            {NAV_GROUPS.map((group) => (
              <div key={group.label} className="c-group">
                <div className="c-group-label">{group.label}</div>
                <div>
                  {group.links.map((link) => (
                    <NavLink key={link.href} href={link.href}>
                      {link.label}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>
          <div className="c-user">
            {claims?.email && (
              <div>
                {claims.email}
                {claims.role ? ` · ${claims.role}` : ""}
              </div>
            )}
            <button type="button" onClick={handleLogout}>
              Log out
            </button>
          </div>
        </aside>
        <main className="c-main">{children}</main>
      </div>
    </div>
  );
}

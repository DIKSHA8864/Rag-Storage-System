"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { NavLink } from "@/components/layout/NavLink";
import { useAuth } from "@/lib/auth/useAuth";
import { isEndUserPath } from "@/lib/sessionIdentity";

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  // The admin console's navigation only ever appears for a signed-in staff
  // member, and never on end-user portal pages (they have their own header).
  const showConsole = isAuthenticated && !isEndUserPath(pathname);

  // The client portal draws its own header and page (app/(client)/layout.tsx).
  if (isEndUserPath(pathname)) {
    return <>{children}</>;
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "1rem 1.5rem",
          borderBottom: "1px solid #e0e0e0",
        }}
      >
        <Link href="/" style={{ fontWeight: 600, textDecoration: "none", color: "inherit" }}>
          AshiLegal
        </Link>

        {showConsole && (
          <nav style={{ display: "flex", gap: "1rem" }}>
            <NavLink href="/dashboard">Dashboard</NavLink>
            <NavLink href="/research">Research</NavLink>
            <NavLink href="/vault">Vault</NavLink>
            <NavLink href="/matters">Matters</NavLink>
            <NavLink href="/intake-checklist">Intake</NavLink>
            <NavLink href="/requests">Requests</NavLink>
            <NavLink href="/users">Users</NavLink>
            <NavLink href="/prompts">Prompts</NavLink>
            <NavLink href="/billing">Billing</NavLink>
            <NavLink href="/activity">Activity</NavLink>
            <NavLink href="/analytics">Analytics</NavLink>
            <NavLink href="/settings">Settings</NavLink>
          </nav>
        )}

        {showConsole && (
          <button onClick={handleLogout} style={{ cursor: "pointer" }}>
            Log out
          </button>
        )}
      </header>

      <main style={{ flex: 1, padding: "1.5rem" }}>{children}</main>
    </div>
  );
}
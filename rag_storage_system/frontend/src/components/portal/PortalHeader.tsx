"use client";

import { useRouter } from "next/navigation";

import { NavLink } from "@/components/layout/NavLink";
import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";

/** The signed-in end user's own navigation - only ever Ask and Intake; no library/admin pages exist on this side. */
export function PortalHeader() {
  const { isAuthenticated, email, logout } = useEndUserAuth();
  const router = useRouter();

  if (!isAuthenticated) {
    return null;
  }

  function handleLogout() {
    logout();
    router.push("/portal/login");
  }

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        maxWidth: 820,
        margin: "0 auto 1.5rem",
        padding: "0.5rem 0",
        borderBottom: "1px solid #eee",
        gap: "1rem",
        flexWrap: "wrap",
      }}
    >
      <nav style={{ display: "flex", gap: "1rem" }}>
        <NavLink href="/ask">Ask</NavLink>
        <NavLink href="/intake">My Intake</NavLink>
      </nav>
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
        <span style={{ color: "#666", fontSize: "0.85rem" }}>{email}</span>
        <button type="button" onClick={handleLogout}>
          Sign out
        </button>
      </div>
    </div>
  );
}

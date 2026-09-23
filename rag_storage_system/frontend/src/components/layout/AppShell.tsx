"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth/useAuth";

export function AppShell({ children }: { children: ReactNode }) {
  const { isAuthenticated, logout } = useAuth();
  const router = useRouter();

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

          {isAuthenticated && (
          <nav style={{ display: "flex", gap: "1rem" }}>
            <Link href="/dashboard">Dashboard</Link>
            <Link href="/research">Research</Link>
            <Link href="/vault">Vault</Link>
          </nav>
        )}

        {isAuthenticated && (
          <button onClick={handleLogout} style={{ cursor: "pointer" }}>
            Log out
          </button>
        )}
      </header>

      <main style={{ flex: 1, padding: "1.5rem" }}>{children}</main>
    </div>
  );
}
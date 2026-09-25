"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import { loadEndUserSession } from "@/lib/clientAuth/endUserSessionStorage";
import { END_USER_HOME, STAFF_HOME } from "@/lib/sessionIdentity";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/** Entry point: an already signed-in administrator goes straight to the dashboard; everyone else picks how to sign in. */
export default function HomePage() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated) {
      router.replace(STAFF_HOME);
    } else if (loadEndUserSession()) {
      router.replace(END_USER_HOME);
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || isAuthenticated) {
    return <LoadingSpinner />;
  }

  return (
    <div style={{ maxWidth: 420, margin: "4rem auto", padding: "0 1rem", textAlign: "center" }}>
      <h1>Welcome to AshiLegal</h1>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: "2rem" }}>
        <Link
          href="/portal/login"
          style={{ padding: "0.75rem", border: "1px solid #1a5fb4", borderRadius: 6, textDecoration: "none", fontWeight: 600 }}
        >
          Sign in
        </Link>
        <Link href="/portal/signup" style={{ fontSize: "0.9rem" }}>
          First time? Create your account
        </Link>
        <Link href="/login" style={{ fontSize: "0.85rem", color: "#777", marginTop: "1.5rem" }}>
          Administrator sign in
        </Link>
      </div>
    </div>
  );
}

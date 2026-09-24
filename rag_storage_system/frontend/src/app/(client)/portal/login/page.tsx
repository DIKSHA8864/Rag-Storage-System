"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

export default function PortalLoginPage() {
  const { login, isAuthenticated, isLoading } = useEndUserAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/ask");
    }
  }, [isLoading, isAuthenticated, router]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await login(email, password);
      router.push("/ask");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading || isAuthenticated) {
    return <LoadingSpinner label="Checking your session..." />;
  }

  return (
    <div style={{ maxWidth: 380, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Sign in</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>Use the email address your administrator invited.</p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            disabled={isSubmitting}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            disabled={isSubmitting}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        {error && <ErrorMessage message={error} />}

        <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
          {isSubmitting ? "Signing in..." : "Sign in"}
        </button>
      </form>

      <div style={{ marginTop: "1.25rem", display: "flex", flexDirection: "column", gap: "0.4rem", fontSize: "0.9rem" }}>
        <Link href="/portal/signup">First time here? Create your account</Link>
        <Link href="/portal/forgot-password">Forgot your password?</Link>
        <Link href="/login" style={{ color: "#777" }}>
          Administrator? Sign in here
        </Link>
      </div>
    </div>
  );
}

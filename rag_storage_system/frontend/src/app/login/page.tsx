"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

export default function LoginPage() {
  const { login, isAuthenticated, isLoading: isSessionLoading } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Already logged in (e.g. navigated back to /login manually, or a
  // stored session was found on load) - go straight to the protected
  // area instead of showing the form again.
  useEffect(() => {
    if (!isSessionLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isSessionLoading, isAuthenticated, router]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  // Checking for an existing session, or one was just found and the
  // redirect above is about to fire - don't flash the form either way.
  if (isSessionLoading || isAuthenticated) {
    return <LoadingSpinner label="Checking your session..." />;
  }

  return (
    <div className="c-auth" style={{ maxWidth: 360, margin: "3rem auto" }}>
      <h1>Administrator Login</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        Not an administrator? <Link href="/portal/login">Sign in to the user portal</Link>.
      </p>

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
          {isSubmitting ? "Logging in..." : "Log in"}
        </button>
      </form>
    </div>
  );
}
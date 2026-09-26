"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { completeDropboxConnect } from "@/lib/api/dropbox";
import { useAuth } from "@/lib/auth/useAuth";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * Where Dropbox sends the owner back after "Allow" (the redirect URI
 * registered for the AshiLegal Dropbox app). Hands the one-time code and
 * the signed state to the API, then returns to the Vault page.
 */
export default function DropboxReturnPage() {
  const { token } = useAuth();
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  // A code can be used once; never send it twice (React runs effects twice in development).
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (params.get("error") || !code || !state) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessage(
        params.get("error") === "access_denied"
          ? "Dropbox wasn't connected - access was not allowed."
          : "Dropbox didn't send a sign-in code back. Please try connecting again."
      );
      return;
    }

    completeDropboxConnect(code, state, token)
      .then(() => router.replace("/vault"))
      .catch((err) => setMessage(err instanceof ApiError ? err.message : "Dropbox couldn't be connected. Please try again."));
  }, [token, router]);

  if (!message) return <LoadingSpinner label="Connecting Dropbox..." />;

  return (
    <div style={{ maxWidth: 560, margin: "3rem auto" }}>
      <h1>Dropbox</h1>
      <p>{message}</p>
      <Link href="/vault">Back to the Vault</Link>
    </div>
  );
}

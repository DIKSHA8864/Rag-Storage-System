"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { completeSignup, requestSignupCode } from "@/lib/api/endUserAuth";
import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";
import { CodeAndPasswordForm } from "@/components/portal/CodeAndPasswordForm";
import { EmailStepForm } from "@/components/portal/EmailStepForm";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * One-time account creation: only an email the administrator invited
 * (POST /admin/users) can finish this - the backend checks, and the
 * 6-digit code proves the person owns that inbox.
 */
export default function PortalSignupPage() {
  const { startSession, isAuthenticated, isLoading } = useEndUserAuth();
  const router = useRouter();

  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/ask");
    }
  }, [isLoading, isAuthenticated, router]);

  async function sendCode(targetEmail: string) {
    setError(null);
    setIsSubmitting(true);
    try {
      const response = await requestSignupCode(targetEmail);
      setEmail(targetEmail);
      setInfo(response.detail);
      setStep("code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the code. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleComplete(code: string, password: string) {
    setError(null);
    setIsSubmitting(true);
    try {
      startSession(await completeSignup(email, code, password));
      router.push("/ask");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading || isAuthenticated) {
    return <LoadingSpinner label="Checking your session..." />;
  }

  return (
    <div className="p-auth" style={{ maxWidth: 380, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Create your account</h1>

      {step === "email" ? (
        <>
          <p style={{ color: "#666", fontSize: "0.9rem" }}>
            Enter the email address your administrator invited. We&apos;ll email you a 6-digit code to confirm it&apos;s you.
          </p>
          <EmailStepForm
            initialEmail={email}
            submitLabel="Send code"
            isSubmitting={isSubmitting}
            error={error}
            onSubmit={sendCode}
          />
        </>
      ) : (
        <CodeAndPasswordForm
          email={email}
          info={info}
          submitLabel="Create account"
          isSubmitting={isSubmitting}
          error={error}
          onSubmit={handleComplete}
          onResend={() => sendCode(email)}
          onChangeEmail={() => {
            setStep("email");
            setError(null);
          }}
        />
      )}

      <p style={{ marginTop: "1.25rem", fontSize: "0.9rem" }}>
        Already have an account? <Link href="/portal/login">Sign in</Link>
      </p>
    </div>
  );
}

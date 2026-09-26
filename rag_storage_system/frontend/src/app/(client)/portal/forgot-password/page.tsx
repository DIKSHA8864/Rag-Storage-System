"use client";

import Link from "next/link";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { completePasswordReset, requestPasswordResetCode } from "@/lib/api/endUserAuth";
import { CodeAndPasswordForm } from "@/components/portal/CodeAndPasswordForm";
import { EmailStepForm } from "@/components/portal/EmailStepForm";

/** Resetting the password also signs this account out everywhere else (the backend invalidates every existing session). */
export default function ForgotPasswordPage() {
  const [step, setStep] = useState<"email" | "code" | "done">("email");
  const [email, setEmail] = useState("");
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function sendCode(targetEmail: string) {
    setError(null);
    setIsSubmitting(true);
    try {
      const response = await requestPasswordResetCode(targetEmail);
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
      await completePasswordReset(email, code, password);
      setStep("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reset your password. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="p-auth" style={{ maxWidth: 380, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Reset your password</h1>

      {step === "email" && (
        <>
          <p style={{ color: "#666", fontSize: "0.9rem" }}>
            Enter your account email. We&apos;ll send a 6-digit code to reset your password.
          </p>
          <EmailStepForm
            initialEmail={email}
            submitLabel="Send code"
            isSubmitting={isSubmitting}
            error={error}
            onSubmit={sendCode}
          />
        </>
      )}

      {step === "code" && (
        <CodeAndPasswordForm
          email={email}
          info={info}
          submitLabel="Set new password"
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

      {step === "done" && (
        <p style={{ color: "#2e6b2e" }}>
          Your password has been changed. <Link href="/portal/login">Sign in with your new password</Link>.
        </p>
      )}

      {step !== "done" && (
        <p style={{ marginTop: "1.25rem", fontSize: "0.9rem" }}>
          <Link href="/portal/login">Back to sign in</Link>
        </p>
      )}
    </div>
  );
}

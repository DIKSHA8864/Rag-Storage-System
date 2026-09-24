"use client";

import { useState, type FormEvent } from "react";

import { ErrorMessage } from "@/components/ui/ErrorMessage";

const MIN_PASSWORD_LENGTH = 8;

interface CodeAndPasswordFormProps {
  email: string;
  info: string | null;
  submitLabel: string;
  isSubmitting: boolean;
  error: string | null;
  onSubmit: (code: string, password: string) => void;
  onResend: () => void;
  onChangeEmail: () => void;
}

/** Step 2 of signup and password reset - shared so both enforce the same code format and password rules. */
export function CodeAndPasswordForm({
  email,
  info,
  submitLabel,
  isSubmitting,
  error,
  onSubmit,
  onResend,
  onChangeEmail,
}: CodeAndPasswordFormProps) {
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLocalError(null);

    if (!/^\d{6}$/.test(code.trim())) {
      setLocalError("Enter the 6-digit code from the email.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setLocalError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirmPassword) {
      setLocalError("The two passwords don't match.");
      return;
    }

    onSubmit(code.trim(), password);
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      {info && <p style={{ color: "#2e6b2e", fontSize: "0.9rem", margin: 0 }}>{info}</p>}
      <p style={{ fontSize: "0.9rem", margin: 0 }}>
        Code sent to <strong>{email}</strong>{" "}
        <button type="button" onClick={onChangeEmail} disabled={isSubmitting} style={{ fontSize: "0.8rem" }}>
          Change
        </button>
      </p>

      <label>
        6-digit code
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          required
          disabled={isSubmitting}
          style={{ display: "block", width: "100%", letterSpacing: "0.3em" }}
        />
      </label>

      <label>
        New password (at least {MIN_PASSWORD_LENGTH} characters)
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
          disabled={isSubmitting}
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label>
        Confirm password
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          autoComplete="new-password"
          disabled={isSubmitting}
          style={{ display: "block", width: "100%" }}
        />
      </label>

      {(localError || error) && <ErrorMessage message={localError ?? error ?? ""} />}

      <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
        {isSubmitting ? "Please wait..." : submitLabel}
      </button>
      <button type="button" onClick={onResend} disabled={isSubmitting} style={{ fontSize: "0.85rem" }}>
        Send a new code
      </button>
    </form>
  );
}

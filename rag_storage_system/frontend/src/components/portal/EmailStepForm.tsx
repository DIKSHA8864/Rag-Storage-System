"use client";

import { useState, type FormEvent } from "react";

import { ErrorMessage } from "@/components/ui/ErrorMessage";

interface EmailStepFormProps {
  initialEmail: string;
  submitLabel: string;
  isSubmitting: boolean;
  error: string | null;
  onSubmit: (email: string) => void;
}

/** Step 1 of signup and password reset: which email to send the one-time code to. */
export function EmailStepForm({ initialEmail, submitLabel, isSubmitting, error, onSubmit }: EmailStepFormProps) {
  const [email, setEmail] = useState(initialEmail);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit(email.trim());
  }

  return (
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

      {error && <ErrorMessage message={error} />}

      <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
        {isSubmitting ? "Sending..." : submitLabel}
      </button>
    </form>
  );
}

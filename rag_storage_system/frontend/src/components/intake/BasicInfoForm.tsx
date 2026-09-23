"use client";

import { useState, type FormEvent } from "react";

import { ErrorMessage } from "@/components/ui/ErrorMessage";

interface BasicInfoFormProps {
  onSubmit: (name: string) => void;
  isSubmitting: boolean;
  error: string | null;
}

/**
 * Collects only what the backend actually has a real field for: the
 * intake session's `title` (app/api/schemas.py's
 * IntakeSessionCreateRequest). There is no separate client-record
 * schema on the backend today, so nothing else is asked here.
 */
export function BasicInfoForm({ onSubmit, isSubmitting, error }: BasicInfoFormProps) {
  const [name, setName] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit(name);
  }

  return (
    <div style={{ maxWidth: 420, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Before we begin / Antes de comenzar</h1>
      <p style={{ color: "#666" }}>What&apos;s your name? / Cual es su nombre?</p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: "1rem" }}>
        <label>
          Full name / Nombre completo
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isSubmitting}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        {error && <ErrorMessage message={error} />}

        <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
          {isSubmitting ? "Starting... / Iniciando..." : "Begin / Comenzar"}
        </button>
      </form>
    </div>
  );
}
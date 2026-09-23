"use client";

import { useState, type FormEvent } from "react";

import { ErrorMessage } from "@/components/ui/ErrorMessage";

interface AccessCodeFormProps {
  onSubmit: (code: string) => void;
  isSubmitting: boolean;
  error: string | null;
}

/**
 * The public intake landing screen. The access code is the real
 * X-End-User-Key the firm issued when creating this Client's Matter
 * (POST /admin/matters) - there is no self-registration; this form
 * only ever verifies a real code against the backend, never a fake
 * or locally-generated one.
 */
export function AccessCodeForm({ onSubmit, isSubmitting, error }: AccessCodeFormProps) {
  const [code, setCode] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = code.trim();
    if (trimmed === "") return;
    onSubmit(trimmed);
  }

  return (
    <div style={{ maxWidth: 420, margin: "3rem auto", padding: "0 1rem" }}>
      <h1>Welcome / Bienvenido</h1>
      <p style={{ color: "#666" }}>
        Enter the access code your attorney&apos;s office gave you to begin your intake.
        <br />
        Ingrese el codigo de acceso que le proporciono la oficina de su abogado para comenzar su admision.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: "1rem" }}>
        <label>
          Access code / Codigo de acceso
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            disabled={isSubmitting}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        {error && <ErrorMessage message={error} />}

        <button type="submit" disabled={isSubmitting || code.trim() === ""} aria-busy={isSubmitting}>
          {isSubmitting ? "Checking... / Verificando..." : "Continue / Continuar"}
        </button>
      </form>
    </div>
  );
}
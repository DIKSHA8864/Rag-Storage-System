"use client";

import { useState, type FormEvent } from "react";

import { ErrorMessage } from "@/components/ui/ErrorMessage";
import type { MatterCreatedResponse } from "@/lib/api/types";

interface CreateMatterFormProps {
  onSubmit: (name: string) => Promise<MatterCreatedResponse | void>;
  isSubmitting: boolean;
  error: string | null;
}

/**
 * Creates a real Matter via POST /admin/matters - the returned
 * api_key is shown in plaintext exactly once (the backend never
 * stores or returns it again), so this is the only place it will
 * ever be visible. It's an API credential (X-End-User-Key) for
 * integrations - people sign in to the web portal with their own
 * account instead (invited from the Users page), which gets its own
 * personal Matter automatically.
 */
export function CreateMatterForm({ onSubmit, isSubmitting, error }: CreateMatterFormProps) {
  const [name, setName] = useState("");
  const [created, setCreated] = useState<MatterCreatedResponse | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") return;

    const result = await onSubmit(trimmed);
    if (result) {
      setCreated(result);
      setName("");
    }
  }

  return (
    <div>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New matter name"
          disabled={isSubmitting}
          style={{ flex: 1 }}
        />
        <button type="submit" disabled={isSubmitting || name.trim() === ""}>
          {isSubmitting ? "Creating..." : "Create matter"}
        </button>
      </form>

      {error && <ErrorMessage message={error} />}

      {created && (
        <div style={{ marginTop: "0.75rem", padding: "0.75rem", border: "1px solid #d9a441", borderRadius: 4, background: "#fff8e6" }}>
          <p style={{ margin: "0 0 0.35rem 0", fontWeight: 600, color: "#8a6116" }}>
            &quot;{created.name}&quot; created - copy this access code now, it will never be shown again:
          </p>
          <code style={{ display: "block", padding: "0.5rem", background: "#fff", borderRadius: 4, wordBreak: "break-all" }}>
            {created.api_key}
          </code>
          <p style={{ margin: "0.5rem 0 0 0", fontSize: "0.8rem", color: "#666" }}>
            This code is for API integrations only. To give a person access to the web portal, invite their email
            from the Users page - each person gets their own account and their own private Matter automatically.
          </p>
        </div>
      )}
    </div>
  );
}
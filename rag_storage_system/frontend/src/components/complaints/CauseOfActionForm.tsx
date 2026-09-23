"use client";

import { useState } from "react";

import { createCauseOfAction } from "@/lib/api/complaints";
import { ApiError } from "@/lib/api/client";
import type { CauseOfActionInfo } from "@/lib/api/types";
import { ErrorMessage } from "@/components/ui/ErrorMessage";

interface CauseOfActionFormProps {
  token: string;
  onCreated: (cause: CauseOfActionInfo) => void;
  onAuthFailure: () => void;
}

export function CauseOfActionForm({ token, onCreated, onAuthFailure }: CauseOfActionFormProps) {
  const [category, setCategory] = useState("");
  const [name, setName] = useState("");
  const [elementsText, setElementsText] = useState("");
  const [authorityCitation, setAuthorityCitation] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const elements = elementsText
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);

    if (!category.trim() || !name.trim() || elements.length === 0 || !authorityCitation.trim()) {
      setError("Category, name, at least one element, and authority citation are all required.");
      return;
    }

    setIsSubmitting(true);
    try {
      const cause = await createCauseOfAction(
        { category: category.trim(), name: name.trim(), elements, authority_citation: authorityCitation.trim() },
        token
      );
      onCreated(cause);
      setCategory("");
      setName("");
      setElementsText("");
      setAuthorityCitation("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not save this cause of action.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      {error && <ErrorMessage message={error} />}

      <label style={{ display: "flex", flexDirection: "column", fontSize: "0.85rem", gap: "0.25rem" }}>
        Category
        <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. Employment" />
      </label>

      <label style={{ display: "flex", flexDirection: "column", fontSize: "0.85rem", gap: "0.25rem" }}>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Wrongful Termination" />
      </label>

      <label style={{ display: "flex", flexDirection: "column", fontSize: "0.85rem", gap: "0.25rem" }}>
        Elements (one per line)
        <textarea
          value={elementsText}
          onChange={(e) => setElementsText(e.target.value)}
          rows={4}
          placeholder={"Element 1\nElement 2\nElement 3"}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", fontSize: "0.85rem", gap: "0.25rem" }}>
        Authority citation
        <textarea
          value={authorityCitation}
          onChange={(e) => setAuthorityCitation(e.target.value)}
          rows={2}
          placeholder="Curated citation text"
        />
      </label>

      <button type="submit" disabled={isSubmitting}>
        {isSubmitting ? "Saving..." : "Save cause of action"}
      </button>
    </form>
  );
}

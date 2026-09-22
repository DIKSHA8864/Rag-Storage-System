"use client";

import { useState, type FormEvent } from "react";

interface ResearchQueryFormProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
}

export function ResearchQueryForm({ onSubmit, isLoading }: ResearchQueryFormProps) {
  const [query, setQuery] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed === "") return;
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <label htmlFor="research-query" style={{ fontWeight: 600 }}>
        Research question
      </label>
      <textarea
        id="research-query"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="e.g. Is an employer required to pay overtime after 8 hours in a single day?"
        rows={3}
        maxLength={1000}
        required
        disabled={isLoading}
        style={{ width: "100%", fontFamily: "inherit", fontSize: "1rem", padding: "0.5rem" }}
      />

      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button type="submit" disabled={isLoading || query.trim() === ""} aria-busy={isLoading}>
          {isLoading ? "Researching..." : "Ask"}
        </button>
        {query !== "" && (
          <button type="button" onClick={() => setQuery("")} disabled={isLoading}>
            Clear
          </button>
        )}
      </div>
    </form>
  );
}
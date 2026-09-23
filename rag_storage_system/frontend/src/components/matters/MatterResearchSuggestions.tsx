"use client";

import { useCallback, useEffect, useState } from "react";

import { getMatterResearchSuggestions } from "@/lib/api/matters";
import { ApiError } from "@/lib/api/client";
import type { MatterResearchSuggestionsResponse } from "@/lib/api/types";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

interface MatterResearchSuggestionsProps {
  matterId: number;
  sessionId: number;
  token: string;
  onAuthFailure: () => void;
}

/**
 * Retrieval-grounded suggestions generated from this Matter's own
 * intake facts (app/report/rag_analysis.py's gather_fact_support(),
 * reused - not a second RAG system). Deliberately separate from
 * MatterResearchPanel's citation-grounded Q&A answer: these are
 * exploratory pointers, never cited legal authority, never a legal
 * conclusion.
 */
export function MatterResearchSuggestions({ matterId, sessionId, token, onAuthFailure }: MatterResearchSuggestionsProps) {
  const [data, setData] = useState<MatterResearchSuggestionsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSuggestions = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await getMatterResearchSuggestions(matterId, sessionId, token);
      setData(response);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load research suggestions.");
    } finally {
      setIsLoading(false);
    }
  }, [matterId, sessionId, token, onAuthFailure]);

  useEffect(() => {
    // Fetching when the selected session changes is exactly what this
    // effect is for - same legitimate case as every other page-load
    // fetch in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadSuggestions();
  }, [loadSuggestions]);

  if (isLoading) {
    return <LoadingSpinner label="Loading research suggestions..." />;
  }

  if (error) {
    return <ErrorMessage message={error} />;
  }

  if (!data || data.suggestions.length === 0) {
    return <p style={{ color: "#777", fontSize: "0.85rem" }}>No research suggestions yet for this session&apos;s facts.</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <p style={{ fontSize: "0.8rem", color: "#a15c00" }}>{data.disclaimer}</p>
      {data.suggestions.map((suggestion, index) => (
        <div
          key={index}
          style={{ border: "1px solid #e5e5e5", borderRadius: 4, padding: "0.5rem 0.75rem", background: "#fff8e6" }}
        >
          <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.85rem" }}>
            <strong>Fact:</strong> {suggestion.fact_text}
          </p>
          <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.8rem", color: "#666" }}>
            Research suggestions (NOT cited authority - attorney must verify):
          </p>
          <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
            {suggestion.citations.map((citation, citationIndex) => (
              <li key={citationIndex} style={{ fontSize: "0.8rem" }}>
                {citation.filename} ({citation.category})
                {citation.section && ` - ${citation.section}`}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

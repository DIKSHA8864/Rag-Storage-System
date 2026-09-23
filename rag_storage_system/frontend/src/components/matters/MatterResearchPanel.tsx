"use client";

import { useState } from "react";

import { matterResearchAsk } from "@/lib/api/matters";
import type { OwnerResearchResponse } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ResearchQueryForm } from "@/components/research/ResearchQueryForm";
import { AnswerPanel } from "@/components/research/AnswerPanel";
import { SourcesPanel } from "@/components/research/SourcesPanel";

interface MatterResearchPanelProps {
  matterId: number;
  token: string;
  onAuthFailure: () => void;
}

/**
 * Matter-scoped research - calls the real POST
 * /admin/matters/{id}/research, which reuses the exact same
 * stream_grounded_answer() every other research surface in this app
 * already uses, fed this Matter's own documents plus the Owner's
 * library via retrieve_for_matter() - never a second RAG
 * implementation, and never another Matter's documents (enforced
 * server-side, not just a UI filter).
 */
export function MatterResearchPanel({ matterId, token, onAuthFailure }: MatterResearchPanelProps) {
  const [result, setResult] = useState<OwnerResearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleAsk(query: string) {
    setError(null);
    setResult(null);
    setIsLoading(true);

    try {
      const response = await matterResearchAsk(matterId, { query }, token);
      setResult(response);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div>
      <p style={{ color: "#666", fontSize: "0.85rem" }}>
        Ask a question grounded in this Matter&apos;s own documents and the firm&apos;s legal library. Sources from
        this Matter are labeled separately from library material.
      </p>

      <ResearchQueryForm onSubmit={handleAsk} isLoading={isLoading} />

      <div style={{ marginTop: "1rem" }}>
        {isLoading && <LoadingSpinner label="Retrieving and generating an answer..." />}
        {error && <ErrorMessage message={error} />}

        {result && !isLoading && (
          <>
            <AnswerPanel answer={result.answer} hasSupport={result.sources.length > 0} sources={result.sources} />
            <SourcesPanel sources={result.sources} />
          </>
        )}
      </div>
    </div>
  );
}
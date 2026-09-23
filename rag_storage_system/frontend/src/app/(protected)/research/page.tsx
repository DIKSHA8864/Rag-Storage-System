"use client";

import { useState } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import { askResearch, exportResearch } from "@/lib/api/research";
import type { OwnerResearchResponse } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ResearchQueryForm } from "@/components/research/ResearchQueryForm";
import { AnswerPanel } from "@/components/research/AnswerPanel";
import { SourcesPanel } from "@/components/research/SourcesPanel";

/**
 * The real Owner Research Console - authenticated Owner/Attorney/
 * Paralegal only (enforced by app/(protected)/layout.tsx's
 * ProtectedRoute), backed entirely by the real POST /research/ask
 * (app/api/storage_api.py's owner_research_ask(), which reuses the
 * exact same retrieval + citation-grounded Claude-or-template
 * generation the End User path already uses - see
 * app/analysis/answer_generation.py's stream_grounded_answer()).
 *
 * Export (POST /research/export) renders exactly this same answer and
 * these same sources as a .docx/.pdf file - it never re-runs
 * retrieval or generation, so the exported file can never say
 * something different from what's on screen.
 *
 * This component never generates, alters, reorders, or filters the
 * answer or sources it receives - it only renders what the backend
 * returned, and only ever calls the two existing endpoints.
 */
export default function ResearchPage() {
  const { token, logout } = useAuth();

  const [result, setResult] = useState<OwnerResearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function handleAsk(query: string) {
    setError(null);
    setExportError(null);
    setResult(null);
    setIsLoading(true);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }

      const response = await askResearch({ query }, token);
      setResult(response);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleExport(format: "docx" | "pdf") {
    if (!result) return;

    setExportError(null);
    setIsExporting(true);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }

      const blob = await exportResearch(
        { query: result.query, answer: result.answer, sources: result.sources, format },
        token
      );

      downloadBlob(blob, `research-answer.${format}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setExportError(err instanceof ApiError ? err.message : "Export failed. Please try again.");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h1>Research Console</h1>
      <p style={{ color: "#666" }}>
        Ask a question against the firm&apos;s library. Every answer is grounded in retrieved
        library material only - if the library doesn&apos;t support an answer, that is stated
        directly rather than guessed at.
      </p>

      <ResearchQueryForm onSubmit={handleAsk} isLoading={isLoading} />

      <div style={{ marginTop: "1.5rem" }}>
        {isLoading && <LoadingSpinner label="Retrieving and generating an answer..." />}

        {error && <ErrorMessage message={error} />}

        {result && !isLoading && (
          <>
            <AnswerPanel
              answer={result.answer}
              hasSupport={result.sources.length > 0}
              sources={result.sources}
            />
            <SourcesPanel sources={result.sources} />

            <div style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <button type="button" onClick={() => handleExport("docx")} disabled={isExporting}>
                {isExporting ? "Exporting..." : "Export as DOCX"}
              </button>
              <button type="button" onClick={() => handleExport("pdf")} disabled={isExporting}>
                {isExporting ? "Exporting..." : "Export as PDF"}
              </button>
            </div>

            {exportError && <ErrorMessage message={exportError} />}
          </>
        )}
      </div>
    </div>
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
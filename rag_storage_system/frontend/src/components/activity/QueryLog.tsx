"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { getQueryLog } from "@/lib/api/settings";
import type { QueryLogEntry } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

const PAGE_SIZE = 50;

const PURPOSE_LABELS: Record<string, string> = {
  end_user_query: "Ask (staff)",
  owner_research: "Research",
  matter_research: "Matter research",
  relevance_filter: "Relevance check",
  narrative_generation: "Report narrative",
  vision_captioning: "Image description",
};

// app/analysis/answer_generation.py's citation_check_result values.
const OUTCOMES: Record<string, { label: string; background: string; color: string }> = {
  grounded: { label: "Answered - citations verified", background: "#eaf6ea", color: "#2e6b2e" },
  template_only: { label: "Answered - library excerpts (no AI)", background: "#eaf1fb", color: "#1a5fb4" },
  insufficient_evidence: { label: "No authority in library", background: "#f0f0f0", color: "#555" },
  relevance_check_unavailable: { label: "Check unavailable - not answered", background: "#fdecea", color: "#c0392b" },
  fabricated_discarded: { label: "AI cited outside library - replaced", background: "#fff8e6", color: "#8a6116" },
  claude_error_fallback: { label: "AI error - excerpts shown", background: "#fff8e6", color: "#8a6116" },
  generation_error: { label: "Error", background: "#fdecea", color: "#c0392b" },
};

export function QueryLog() {
  const { token, logout } = useAuth();

  const [entries, setEntries] = useState<QueryLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [questionsOnly, setQuestionsOnly] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (!token) throw new ApiError(401, "Session expired. Please log in again.");
      const page = await getQueryLog(token, { limit: PAGE_SIZE, offset, questionsOnly });
      setEntries(page.entries);
      setTotal(page.total);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load the activity log.");
    } finally {
      setIsLoading(false);
    }
  }, [token, logout, offset, questionsOnly]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const cell = { padding: "0.4rem 0.5rem", borderBottom: "1px solid #eee", verticalAlign: "top" as const };

  return (
    <div>
      <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <label style={{ fontSize: "0.9rem" }}>
          <input
            type="checkbox"
            checked={questionsOnly}
            onChange={(e) => {
              setOffset(0);
              setQuestionsOnly(e.target.checked);
            }}
          />{" "}
          Questions only (hide background AI calls)
        </label>
        <span style={{ fontSize: "0.85rem", color: "#777" }}>{total} total</span>
      </div>

      {error && <ErrorMessage message={error} />}
      {isLoading ? (
        <LoadingSpinner label="Loading activity..." />
      ) : entries.length === 0 ? (
        <p style={{ color: "#777" }}>Nothing recorded yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "#555" }}>
                <th style={cell}>When</th>
                <th style={cell}>Where</th>
                <th style={cell}>Question</th>
                <th style={cell}>Outcome</th>
                <th style={cell}>Sources found</th>
                <th style={cell}>Model / tokens</th>
                <th style={cell}>Time</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const outcome = entry.citation_check_result ? OUTCOMES[entry.citation_check_result] : undefined;
                return (
                  <tr key={entry.id}>
                    <td style={{ ...cell, whiteSpace: "nowrap" }}>{new Date(entry.created_at).toLocaleString()}</td>
                    <td style={cell}>
                      {PURPOSE_LABELS[entry.purpose] ?? entry.purpose}
                      {entry.matter_id ? ` (Matter ${entry.matter_id})` : ""}
                    </td>
                    <td style={{ ...cell, maxWidth: 320 }}>{entry.query_text ?? "-"}</td>
                    <td style={cell}>
                      {outcome ? (
                        <span style={{ background: outcome.background, color: outcome.color, borderRadius: 10, padding: "0.1rem 0.45rem" }}>
                          {outcome.label}
                        </span>
                      ) : (
                        entry.citation_check_result ?? "-"
                      )}
                    </td>
                    <td style={cell}>
                      {entry.retrieved_count}
                      {entry.top_score !== null ? ` (best ${entry.top_score.toFixed(2)})` : ""}
                    </td>
                    <td style={cell}>
                      {entry.model}
                      {entry.input_tokens + entry.output_tokens > 0 ? ` - ${entry.input_tokens}/${entry.output_tokens}` : ""}
                    </td>
                    <td style={{ ...cell, whiteSpace: "nowrap" }}>{(entry.latency_ms / 1000).toFixed(1)}s</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
        <button type="button" disabled={offset === 0 || isLoading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Newer
        </button>
        <button type="button" disabled={offset + PAGE_SIZE >= total || isLoading} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Older
        </button>
      </div>
    </div>
  );
}

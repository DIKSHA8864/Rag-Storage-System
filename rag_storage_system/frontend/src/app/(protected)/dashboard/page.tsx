"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import { askResearch } from "@/lib/api/research";
import type { OwnerResearchResponse } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * Foundation smoke-test page only - proves an authenticated session
 * can call the real POST /research/ask and render a real answer +
 * sources. This is NOT the Research Console: no chat history, no
 * streaming, no styling beyond what's needed to read the response.
 */
export default function DashboardPage() {
  const { token, logout } = useAuth();

  const [query, setQuery] = useState("");
  const [result, setResult] = useState<OwnerResearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
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
      }
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <h1>Dashboard</h1>
      <p>You are logged in. This form calls the real POST /research/ask endpoint.</p>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem", margin: "1rem 0" }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask the library a question..."
          required
          style={{ flex: 1 }}
        />
        <button type="submit" disabled={isLoading || query.trim() === ""}>
          Ask
        </button>
      </form>

      {isLoading && <LoadingSpinner label="Retrieving and generating an answer..." />}
      {error && <ErrorMessage message={error} />}

      {result && (
        <div style={{ marginTop: "1rem" }}>
          <h2>Answer</h2>
          <p>{result.answer}</p>

          <h3>Sources</h3>
          {result.sources.length === 0 ? (
            <p>No sources - the library did not support this answer.</p>
          ) : (
            <ul>
              {result.sources.map((source, i) => (
                <li key={i}>
                  {source.filename} ({source.category}
                  {source.section ? `, ${source.section}` : ""}) - score {source.score.toFixed(2)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
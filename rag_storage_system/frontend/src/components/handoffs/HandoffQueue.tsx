"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { claimHandoff, closeHandoff, listHandoffs } from "@/lib/api/handoffs";
import type { HandoffInfo } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

const FILTERS: { value: string | null; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "claimed", label: "In progress" },
  { value: "closed", label: "Closed" },
  { value: null, label: "All" },
];

const METHOD: Record<string, string> = { phone: "Phone call", video: "Video call", email: "Email" };

/** Clients who asked to talk to a person - claim one, contact them, then close it with a note. */
export function HandoffQueue() {
  const { token, logout } = useAuth();
  const [filter, setFilter] = useState<string | null>("open");
  const [requests, setRequests] = useState<HandoffInfo[]>([]);
  const [openCount, setOpenCount] = useState(0);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const failure = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : fallback);
    },
    [logout]
  );

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (!token) throw new ApiError(401, "Session expired. Please log in again.");
      const response = await listHandoffs(filter, token);
      setRequests(response.requests);
      setOpenCount(response.open_count);
    } catch (err) {
      failure(err, "Could not load requests.");
    } finally {
      setIsLoading(false);
    }
  }, [filter, token, failure]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function act(action: () => Promise<unknown>, fallback: string) {
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      failure(err, fallback);
    }
  }

  return (
    <div>
      <div role="group" aria-label="Filter" style={{ display: "flex", gap: "0.35rem", marginBottom: "1rem" }}>
        {FILTERS.map((option) => (
          <button
            key={option.label}
            type="button"
            aria-pressed={filter === option.value}
            onClick={() => setFilter(option.value)}
            style={{ fontWeight: filter === option.value ? 700 : 400 }}
          >
            {option.label}
            {option.value === "open" && openCount > 0 ? ` (${openCount})` : ""}
          </button>
        ))}
      </div>

      {error && <ErrorMessage message={error} />}
      {isLoading ? (
        <LoadingSpinner label="Loading requests..." />
      ) : requests.length === 0 ? (
        <p style={{ color: "#777" }}>No requests here.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {requests.map((request) => (
            <li key={request.id} style={{ border: "1px solid #e5e5e5", borderRadius: 6, padding: "0.75rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                <strong>
                  {METHOD[request.contact_method] ?? request.contact_method}: {request.contact_value}
                </strong>
                <span style={{ fontSize: "0.8rem", color: "#666" }}>{new Date(request.created_at).toLocaleString()}</span>
              </div>
              <div style={{ fontSize: "0.85rem", color: "#444", marginTop: "0.3rem" }}>
                {request.preferred_time && <div>Best time: {request.preferred_time}</div>}
                {request.message && <div>Message: {request.message}</div>}
                <div>
                  Language: {request.language === "es" ? "Spanish" : "English"} - Matter #{request.matter_id}
                  {request.intake_session_id ? ` - intake #${request.intake_session_id}` : ""}
                </div>
                <div>
                  Status: {request.status === "claimed" ? `in progress (${request.claimed_by})` : request.status}
                  {request.closed_note ? ` - ${request.closed_note}` : ""}
                </div>
              </div>
              {request.status !== "closed" && (
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
                  {request.status === "open" && (
                    <button type="button" onClick={() => act(() => claimHandoff(request.id, token ?? ""), "Could not claim.")}>
                      I&apos;ll take it
                    </button>
                  )}
                  <input
                    aria-label={`Note for request ${request.id}`}
                    placeholder="Outcome note (e.g. called, consult booked)"
                    value={notes[request.id] ?? ""}
                    onChange={(e) => setNotes((n) => ({ ...n, [request.id]: e.target.value }))}
                    style={{ flex: 1, minWidth: 220 }}
                  />
                  <button
                    type="button"
                    onClick={() => act(() => closeHandoff(request.id, notes[request.id] ?? "", token ?? ""), "Could not close.")}
                  >
                    Close
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

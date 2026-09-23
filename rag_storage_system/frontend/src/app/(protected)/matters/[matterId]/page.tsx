"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { useAuth } from "@/lib/auth/useAuth";
import { getMatter, getMatterIntakeSessionDetail, listMatterIntakeSessions } from "@/lib/api/matters";
import type { IntakeSessionInfo, MatterInfo, MatterIntakeSessionDetailResponse } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { SessionList } from "@/components/matters/SessionList";
import { SessionDetail } from "@/components/matters/SessionDetail";
import { MatterResearchPanel } from "@/components/matters/MatterResearchPanel";
import { ComplaintGenerator } from "@/components/complaints/ComplaintGenerator";
import { MatterResearchSuggestions } from "@/components/matters/MatterResearchSuggestions";

/**
 * The real Matter Workspace - matter detail, its intake sessions, and
 * Matter-scoped research, all from app/api/storage_api.py's Matter
 * endpoints, every one gated by the same ensure_matter_access()
 * isolation check.
 */
export default function MatterWorkspacePage() {
  const { token, logout } = useAuth();
  const params = useParams<{ matterId: string }>();
  const matterId = Number(params.matterId);

  const [matter, setMatter] = useState<MatterInfo | null>(null);
  const [sessions, setSessions] = useState<IntakeSessionInfo[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [sessionDetail, setSessionDetail] = useState<MatterIntakeSessionDetailResponse | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  const handleAuthFailure = useCallback(() => {
    logout();
  }, [logout]);

  const loadWorkspace = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const [matterResponse, sessionsResponse] = await Promise.all([
        getMatter(matterId, token),
        listMatterIntakeSessions(matterId, token),
      ]);
      setMatter(matterResponse);
      setSessions(sessionsResponse.sessions);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleAuthFailure();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load this matter.");
    } finally {
      setIsLoading(false);
    }
  }, [matterId, token, handleAuthFailure]);

  useEffect(() => {
    if (!Number.isFinite(matterId)) return;
    // Fetching on mount is exactly what this effect is for - same
    // legitimate case as every other page-load fetch in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadWorkspace();
  }, [matterId, loadWorkspace]);

  async function handleSelectSession(sessionId: number) {
    setSelectedSessionId(sessionId);
    setSessionError(null);
    setIsLoadingSession(true);
    setSessionDetail(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const detail = await getMatterIntakeSessionDetail(matterId, sessionId, token);
      setSessionDetail(detail);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleAuthFailure();
        return;
      }
      setSessionError(err instanceof ApiError ? err.message : "Could not load this session.");
    } finally {
      setIsLoadingSession(false);
    }
  }

  if (!Number.isFinite(matterId)) {
    return <ErrorMessage message="Invalid matter." />;
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading matter..." />;
  }

  if (error || !matter) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <ErrorMessage message={error ?? "Matter not found."} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h1>{matter.name}</h1>
      <p style={{ color: matter.is_active ? "#2e7d32" : "#999" }}>{matter.is_active ? "Active" : "Inactive"}</p>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>Intake sessions</h2>
        <SessionList sessions={sessions} selectedSessionId={selectedSessionId} onSelect={handleSelectSession} />

        {isLoadingSession && <LoadingSpinner label="Loading session..." />}
        {sessionError && <ErrorMessage message={sessionError} />}
        {sessionDetail && !isLoadingSession && (
          <div style={{ marginTop: "1rem" }}>
            <SessionDetail detail={sessionDetail} />
          </div>
        )}

        {selectedSessionId && !isLoadingSession && (
          <div style={{ marginTop: "1rem" }}>
            <h2 style={{ fontSize: "1rem", color: "#555" }}>Complaint generator</h2>
            <ComplaintGenerator sessionId={selectedSessionId} token={token ?? ""} onAuthFailure={handleAuthFailure} />
          </div>
        )}

        {selectedSessionId && !isLoadingSession && (
          <div style={{ marginTop: "1rem" }}>
            <h2 style={{ fontSize: "1rem", color: "#555" }}>Matter research suggestions</h2>
            <MatterResearchSuggestions
              matterId={matterId}
              sessionId={selectedSessionId}
              token={token ?? ""}
              onAuthFailure={handleAuthFailure}
            />
          </div>
        )}
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>Research this matter</h2>
        <MatterResearchPanel matterId={matterId} token={token ?? ""} onAuthFailure={handleAuthFailure} />
      </section>
    </div>
  );
}
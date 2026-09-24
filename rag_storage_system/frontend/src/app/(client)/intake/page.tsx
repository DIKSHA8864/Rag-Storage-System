"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";
import { listIntakeSessions, createIntakeSession } from "@/lib/api/intake";
import type { IntakeSessionInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { BasicInfoForm } from "@/components/intake/BasicInfoForm";
import { InterviewChat } from "@/components/intake/InterviewChat";
import { RequireEndUser } from "@/components/portal/RequireEndUser";
import { clearIntakeSessionId, loadIntakeSessionId, saveIntakeSessionId } from "@/lib/clientAuth/intakeSessionStorage";
import { clearIntakeReportId } from "@/lib/clientAuth/intakeReportStorage";

type Phase = "loading" | "info" | "interview" | "error";

/**
 * The signed-in end user's intake: resumes their most recent intake
 * session if they have one, otherwise asks for basic information and
 * starts a new one. Every session belongs to this user's own personal
 * Matter (app/security/end_user_accounts.py) - the backend never shows
 * one user another user's intake.
 */
function IntakeContent() {
  const { endUserToken, logout } = useEndUserAuth();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("loading");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [isCreatingSession, setIsCreatingSession] = useState(false);

  const handleUnauthorized = useCallback(() => {
    logout();
    router.push("/portal/login");
  }, [logout, router]);

  const resolveNextPhase = useCallback((sessions: IntakeSessionInfo[]) => {
    const savedId = loadIntakeSessionId();
    const savedSession = savedId ? sessions.find((s) => s.id === savedId) : undefined;

    if (savedSession) {
      setSessionId(savedSession.id);
      setPhase("interview");
      return;
    }

    const mostRecent = [...sessions].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )[0];

    if (mostRecent) {
      saveIntakeSessionId(mostRecent.id);
      setSessionId(mostRecent.id);
      setPhase("interview");
      return;
    }

    setPhase("info");
  }, []);

  const loadSessions = useCallback(async () => {
    if (!endUserToken) return;
    setLoadError(null);

    try {
      const response = await listIntakeSessions(endUserToken);
      resolveNextPhase(response.sessions);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleUnauthorized();
        return;
      }
      setLoadError(err instanceof ApiError ? err.message : "Could not connect. Please try again.");
      setPhase("error");
    }
  }, [endUserToken, resolveNextPhase, handleUnauthorized]);

  useEffect(() => {
    // Page-load fetch, same legitimate case as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadSessions();
  }, [loadSessions]);

  async function handleSubmitInfo(name: string) {
    if (!endUserToken) return;

    setInfoError(null);
    setIsCreatingSession(true);

    try {
      const title = name.trim() ? `Intake - ${name.trim()}` : "New intake";
      const session = await createIntakeSession({ title }, endUserToken);
      saveIntakeSessionId(session.id);
      setSessionId(session.id);
      setPhase("interview");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleUnauthorized();
        return;
      }
      setInfoError(err instanceof ApiError ? err.message : "Could not start your intake. Please try again.");
    } finally {
      setIsCreatingSession(false);
    }
  }

  function handleNewIntake() {
    clearIntakeSessionId();
    clearIntakeReportId();
    setSessionId(null);
    setPhase("info");
  }

  if (phase === "loading") {
    return <LoadingSpinner label="Loading..." />;
  }

  if (phase === "error") {
    return (
      <div style={{ maxWidth: 560, margin: "3rem auto", padding: "0 1rem" }}>
        <ErrorMessage message={loadError ?? "Something went wrong."} />
        <button type="button" onClick={loadSessions} style={{ marginTop: "1rem" }}>
          Retry / Reintentar
        </button>
      </div>
    );
  }

  if (phase === "info") {
    return <BasicInfoForm onSubmit={handleSubmitInfo} isSubmitting={isCreatingSession} error={infoError} />;
  }

  if (phase === "interview" && sessionId && endUserToken) {
    return (
      <InterviewChat
        sessionId={sessionId}
        endUserToken={endUserToken}
        onStartOver={handleNewIntake}
        onUnauthorized={handleUnauthorized}
      />
    );
  }

  return <LoadingSpinner label="Loading..." />;
}

export default function IntakePage() {
  return (
    <RequireEndUser>
      <IntakeContent />
    </RequireEndUser>
  );
}

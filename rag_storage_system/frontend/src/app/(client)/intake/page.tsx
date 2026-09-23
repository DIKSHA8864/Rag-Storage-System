"use client";

import { useCallback, useEffect, useState } from "react";

import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";
import { listIntakeSessions, createIntakeSession } from "@/lib/api/intake";
import type { IntakeSessionInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { AccessCodeForm } from "@/components/intake/AccessCodeForm";
import { BasicInfoForm } from "@/components/intake/BasicInfoForm";
import { InterviewChat } from "@/components/intake/InterviewChat";
import { clearIntakeSessionId, loadIntakeSessionId, saveIntakeSessionId } from "@/lib/clientAuth/intakeSessionStorage";

type Phase = "loading" | "code" | "info" | "interview";

/**
 * The real, public Client Intake entry point - covers the landing
 * screen (access code) and basic client information, then hands off
 * into the real conversational interview (InterviewChat), where
 * language selection and terms acceptance are the first two turns the
 * backend itself drives (app/intake_engine/) - not a separate,
 * disconnected frontend-only gate.
 */
export default function IntakePage() {
  const { endUserKey, isLoading: isAuthLoading, isAuthenticated, login, logout } = useEndUserAuth();

  const [phase, setPhase] = useState<Phase>("loading");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [isCreatingSession, setIsCreatingSession] = useState(false);

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

  const verifyAndRoute = useCallback(async () => {
    if (!endUserKey) {
      setPhase("code");
      return;
    }

    try {
      const response = await listIntakeSessions(endUserKey);
      resolveNextPhase(response.sessions);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        setPhase("code");
        return;
      }
      setPhase("code");
      setCodeError(err instanceof ApiError ? err.message : "Could not connect. Please try again.");
    }
  }, [endUserKey, logout, resolveNextPhase]);

  useEffect(() => {
    if (isAuthLoading) return;

    if (!isAuthenticated) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPhase("code");
      return;
    }

    // Fetching once the saved key is known is exactly what this
    // effect is for - same legitimate case as every other page-load
    // fetch in this app.
    verifyAndRoute();
  }, [isAuthLoading, isAuthenticated, verifyAndRoute]);

  async function handleSubmitCode(code: string) {
    setCodeError(null);
    setIsVerifying(true);

    try {
      const sessions = await login(code);
      resolveNextPhase(sessions);
    } catch (err) {
      setCodeError(
        err instanceof ApiError && err.status === 401
          ? "That access code was not recognized. Please check it and try again."
          : err instanceof ApiError
            ? err.message
            : "Could not connect. Please try again."
      );
    } finally {
      setIsVerifying(false);
    }
  }

  async function handleSubmitInfo(name: string) {
    if (!endUserKey) return;

    setInfoError(null);
    setIsCreatingSession(true);

    try {
      const title = name.trim() ? `Intake - ${name.trim()}` : "New intake";
      const session = await createIntakeSession({ title }, endUserKey);
      saveIntakeSessionId(session.id);
      setSessionId(session.id);
      setPhase("interview");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        setPhase("code");
        return;
      }
      setInfoError(err instanceof ApiError ? err.message : "Could not start your intake. Please try again.");
    } finally {
      setIsCreatingSession(false);
    }
  }

  function handleStartOver() {
    clearIntakeSessionId();
    logout();
    setSessionId(null);
    setPhase("code");
  }

  if (phase === "loading") {
    return <LoadingSpinner label="Loading..." />;
  }

  if (phase === "code") {
    return <AccessCodeForm onSubmit={handleSubmitCode} isSubmitting={isVerifying} error={codeError} />;
  }

  if (phase === "info") {
    return <BasicInfoForm onSubmit={handleSubmitInfo} isSubmitting={isCreatingSession} error={infoError} />;
  }

  if (phase === "interview" && sessionId && endUserKey) {
    return <InterviewChat sessionId={sessionId} endUserKey={endUserKey} onStartOver={handleStartOver} />;
  }

  return <LoadingSpinner label="Loading..." />;
}
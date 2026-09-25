"use client";

import { createContext, useCallback, useEffect, useState, type ReactNode } from "react";

import { endUserLogin } from "@/lib/api/endUserAuth";
import type { EndUserSessionResponse } from "@/lib/api/types";
import { markActiveIdentity, reconcileSessions, SESSION_CHANGED_EVENT } from "@/lib/sessionIdentity";
import { clearEndUserSession, loadEndUserSession, saveEndUserSession } from "./endUserSessionStorage";
import { clearIntakeSessionId } from "./intakeSessionStorage";
import { clearIntakeReportId } from "./intakeReportStorage";

interface EndUserAuthContextValue {
  endUserToken: string | null;
  email: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  startSession: (session: EndUserSessionResponse) => void;
  logout: () => void;
}

export const EndUserAuthContext = createContext<EndUserAuthContextValue | undefined>(undefined);

export function EndUserAuthProvider({ children }: { children: ReactNode }) {
  const [endUserToken, setEndUserToken] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // localStorage doesn't exist during SSR, so the saved session can
    // only be read after mount - same case as the Owner session's own
    // hydration effect (lib/auth/AuthContext.tsx).
    reconcileSessions();
    const saved = loadEndUserSession();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEndUserToken(saved?.token ?? null);
    setEmail(saved?.email ?? null);
    setIsLoading(false);

    // A staff sign-in (this tab or another) ends this end-user session.
    const resync = () => {
      const current = loadEndUserSession();
      setEndUserToken(current?.token ?? null);
      setEmail(current?.email ?? null);
    };
    window.addEventListener(SESSION_CHANGED_EVENT, resync);
    window.addEventListener("storage", resync);
    return () => {
      window.removeEventListener(SESSION_CHANGED_EVENT, resync);
      window.removeEventListener("storage", resync);
    };
  }, []);

  const startSession = useCallback((session: EndUserSessionResponse) => {
    saveEndUserSession(session.access_token, session.email, session.expires_in);
    markActiveIdentity("end_user");
    setEndUserToken(session.access_token);
    setEmail(session.email);
  }, []);

  const login = useCallback(
    async (loginEmail: string, password: string) => {
      startSession(await endUserLogin(loginEmail, password));
    },
    [startSession]
  );

  const logout = useCallback(() => {
    clearEndUserSession();
    // The in-progress intake/report ids belong to this user's session -
    // never let them carry over to whoever signs in next on this browser.
    clearIntakeSessionId();
    clearIntakeReportId();
    setEndUserToken(null);
    setEmail(null);
  }, []);

  return (
    <EndUserAuthContext.Provider
      value={{ endUserToken, email, isAuthenticated: endUserToken !== null, isLoading, login, startSession, logout }}
    >
      {children}
    </EndUserAuthContext.Provider>
  );
}

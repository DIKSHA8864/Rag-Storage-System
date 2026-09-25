"use client";

import { createContext, useCallback, useEffect, useState, type ReactNode } from "react";

import { login as apiLogin } from "@/lib/api/auth";
import { markActiveIdentity, reconcileSessions, SESSION_CHANGED_EVENT } from "@/lib/sessionIdentity";
import { clearSession, loadSession, saveSession } from "./token-storage";

interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // localStorage doesn't exist during SSR, so the stored session can
    // only be read after mount - this one-time hydration read is the
    // exception the set-state-in-effect rule is meant to allow.
    reconcileSessions();
    const session = loadSession();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(session?.token ?? null);
    setIsLoading(false);

    // A sign-in on the portal (this tab or another) ends this staff session.
    const resync = () => setToken(loadSession()?.token ?? null);
    window.addEventListener(SESSION_CHANGED_EVENT, resync);
    window.addEventListener("storage", resync);
    return () => {
      window.removeEventListener(SESSION_CHANGED_EVENT, resync);
      window.removeEventListener("storage", resync);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiLogin({ email, password });
    saveSession(response.access_token, response.expires_in);
    markActiveIdentity("staff");
    setToken(response.access_token);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ token, isAuthenticated: token !== null, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}
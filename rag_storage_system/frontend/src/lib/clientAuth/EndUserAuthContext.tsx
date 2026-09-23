"use client";

import { createContext, useCallback, useEffect, useState, type ReactNode } from "react";

import { listIntakeSessions } from "@/lib/api/intake";
import type { IntakeSessionInfo } from "@/lib/api/types";
import { clearEndUserKey, loadEndUserKey, saveEndUserKey } from "./endUserKeyStorage";

interface EndUserAuthContextValue {
  endUserKey: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (key: string) => Promise<IntakeSessionInfo[]>;
  logout: () => void;
}

export const EndUserAuthContext = createContext<EndUserAuthContextValue | undefined>(undefined);

export function EndUserAuthProvider({ children }: { children: ReactNode }) {
  const [endUserKey, setEndUserKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // localStorage doesn't exist during SSR, so the saved access code
    // can only be read after mount - same case as the Owner session's
    // own hydration effect (AuthContext.tsx).
    const saved = loadEndUserKey();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEndUserKey(saved);
    setIsLoading(false);
  }, []);

  const login = useCallback(async (key: string) => {
    // Verifies the access code by actually calling a real, already-
    // needed endpoint - a bad code fails here with a clear 401 instead
    // of silently being stored and failing later.
    const response = await listIntakeSessions(key);
    saveEndUserKey(key);
    setEndUserKey(key);
    return response.sessions;
  }, []);

  const logout = useCallback(() => {
    clearEndUserKey();
    setEndUserKey(null);
  }, []);

  return (
    <EndUserAuthContext.Provider value={{ endUserKey, isAuthenticated: endUserKey !== null, isLoading, login, logout }}>
      {children}
    </EndUserAuthContext.Provider>
  );
}
"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { loadEndUserSession } from "@/lib/clientAuth/endUserSessionStorage";
import { END_USER_HOME } from "@/lib/sessionIdentity";
import { useAuth } from "./useAuth";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * Wrap any page/layout that requires a logged-in Owner/Attorney/
 * Paralegal session (a saved token whose role is one of those - see
 * lib/auth/token-storage.ts). Never renders protected content while
 * the check is in flight. Without a staff session: a signed-in end user
 * is sent to their own area, anyone else to the admin sign-in. The API
 * refuses non-staff tokens on every admin endpoint regardless.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(loadEndUserSession() ? END_USER_HOME : "/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return <LoadingSpinner label="Checking your session..." />;
  }

  if (!isAuthenticated) {
    return null; // redirect is in flight
  }

  return <>{children}</>;
}
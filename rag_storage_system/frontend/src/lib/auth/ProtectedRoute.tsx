"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "./useAuth";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * Wrap any page/layout that requires a logged-in Owner/Attorney/
 * Paralegal session. Redirects to /login if there's no valid token
 * once the initial session check finishes - never renders protected
 * content while that check is still in flight.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
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
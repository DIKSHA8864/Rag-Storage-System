"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useEndUserAuth } from "@/lib/clientAuth/useEndUserAuth";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/** Sends anyone without an end-user session to the portal sign-in page. The backend enforces this independently on every request. */
export function RequireEndUser({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useEndUserAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/portal/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading || !isAuthenticated) {
    return <LoadingSpinner label="Checking your session..." />;
  }

  return <>{children}</>;
}

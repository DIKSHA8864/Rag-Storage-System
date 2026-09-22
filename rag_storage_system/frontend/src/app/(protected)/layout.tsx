import type { ReactNode } from "react";

import { ProtectedRoute } from "@/lib/auth/ProtectedRoute";

/**
 * Every page under app/(protected)/ is gated here, once - a new
 * protected page just needs to live in this folder; it never has to
 * remember to wrap itself in <ProtectedRoute> individually.
 */
export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
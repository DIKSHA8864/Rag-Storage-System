"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import { createMatter, listMatters } from "@/lib/api/matters";
import type { MatterCreatedResponse, MatterInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { MatterList } from "@/components/matters/MatterList";
import { CreateMatterForm } from "@/components/matters/CreateMatterForm";

/**
 * Real Matter list + creation - GET/POST /admin/matters. No fake
 * matters: every row here is a real, isolated End User identity the
 * backend already tracks.
 */
export default function MattersPage() {
  const { token, logout } = useAuth();

  const [matters, setMatters] = useState<MatterInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadMatters = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const response = await listMatters(token);
      setMatters(response.matters);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load matters.");
    } finally {
      setIsLoading(false);
    }
  }, [token, logout]);

  useEffect(() => {
    // Fetching on mount is exactly what this effect is for - same
    // legitimate case as every other page-load fetch in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadMatters();
  }, [loadMatters]);

  async function handleCreate(name: string): Promise<MatterCreatedResponse | void> {
    setCreateError(null);
    setIsCreating(true);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const created = await createMatter({ name }, token);
      await loadMatters();
      return created;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setCreateError(err instanceof ApiError ? err.message : "Could not create matter.");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h1>Matters</h1>
      <p style={{ color: "#666" }}>Each Matter is an isolated Client identity with its own intake and documents.</p>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>Create a matter</h2>
        <CreateMatterForm onSubmit={handleCreate} isSubmitting={isCreating} error={createError} />
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>All matters</h2>
        {isLoading ? (
          <LoadingSpinner label="Loading matters..." />
        ) : error ? (
          <ErrorMessage message={error} />
        ) : (
          <MatterList matters={matters} />
        )}
      </section>
    </div>
  );
}
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import type { VaultSyncStatusResponse } from "@/lib/api/types";
import { getVaultSyncStatus, startVaultSync } from "@/lib/api/vaultSync";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";

const POLL_MS = 3000;

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  ok: { label: "Synced", color: "#2e6b2e" },
  refused: { label: "Stopped - nothing was changed", color: "#8a6116" },
  failed: { label: "Failed", color: "#c0392b" },
};

/**
 * Automatic library sync from a Dropbox / Google Drive folder
 * (app/vault_sync/). Owner-only: shows the source, the last run, and a
 * "Sync now" button. Renders nothing for someone who isn't the Owner.
 */
export function VaultSyncPanel({ onSynced }: { onSynced: () => void }) {
  const { token } = useAuth();
  const [status, setStatus] = useState<VaultSyncStatusResponse | null>(null);
  const [hidden, setHidden] = useState(false);
  // The last run id when "Sync now" was pressed - syncing until a newer run is recorded.
  const [syncStartedAfter, setSyncStartedAfter] = useState<number | null>(null);
  const notifiedRunId = useRef(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setStatus(await getVaultSyncStatus(token));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setHidden(true);
      else setError(err instanceof ApiError ? err.message : "Could not load sync status.");
    }
  }, [token]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const latestRunId = status?.last_run?.id ?? 0;
  const isSyncing = syncStartedAfter !== null && latestRunId <= syncStartedAfter;

  // After "Sync now": poll until a newer run is recorded, then refresh the page's lists once.
  useEffect(() => {
    if (syncStartedAfter === null) return;
    if (!isSyncing) {
      if (latestRunId > notifiedRunId.current) {
        notifiedRunId.current = latestRunId;
        onSynced();
      }
      return;
    }
    const timer = setTimeout(() => void load(), POLL_MS);
    return () => clearTimeout(timer);
  }, [syncStartedAfter, isSyncing, latestRunId, load, onSynced]);

  async function handleSync(allowMassDelete = false) {
    if (!token) return;
    setError(null);
    try {
      setSyncStartedAfter(latestRunId);
      await startVaultSync(token, allowMassDelete);
      await load();
    } catch (err) {
      setSyncStartedAfter(null);
      setError(err instanceof ApiError ? err.message : "Could not start the sync.");
    }
  }

  if (hidden || !status) return error ? <ErrorMessage message={error} /> : null;

  const run = status.last_run;

  return (
    <section style={{ marginTop: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555", margin: 0 }}>Automatic sync</h2>
        {status.configured && (
          <button type="button" onClick={() => handleSync()} disabled={isSyncing}>
            {isSyncing ? "Syncing..." : "Sync now"}
          </button>
        )}
      </div>

      {!status.configured ? (
        <p style={{ fontSize: "0.85rem", color: "#666" }}>
          Off. To keep the library in step with a Dropbox or Google Drive folder automatically, set{" "}
          <code>VAULT_SYNC_DIR</code> (or the <code>DROPBOX_*</code> settings) on the server and run{" "}
          <code>python scripts/vault_sync.py --watch</code>.
        </p>
      ) : (
        <div style={{ fontSize: "0.85rem", color: "#666" }}>
          <p style={{ margin: "0.25rem 0" }}>
            Source: <strong>{status.source}</strong>
            {status.interval_seconds ? ` - checked every ${Math.round(status.interval_seconds / 60)} min when the sync service runs` : ""}
          </p>
          {run ? (
            <>
              <p style={{ margin: "0.25rem 0" }}>
                Last run {new Date(run.finished_at).toLocaleString()}:{" "}
                <strong style={{ color: STATUS_STYLE[run.status]?.color }}>{STATUS_STYLE[run.status]?.label ?? run.status}</strong>
                {run.status === "ok" &&
                  ` - ${run.added} added, ${run.updated} updated, ${run.deleted} removed, ${run.unchanged} unchanged`}
              </p>
              {run.error && <p style={{ margin: "0.25rem 0", color: "#8a6116" }}>{run.error}</p>}
              {run.status === "refused" && run.error?.includes("allow mass delete") && (
                <button type="button" onClick={() => handleSync(true)} disabled={isSyncing}>
                  Yes, remove those files from the library
                </button>
              )}
              {run.skipped.length > 0 && (
                <details style={{ marginTop: "0.25rem" }}>
                  <summary>{run.skipped.length} file(s) skipped</summary>
                  <ul style={{ margin: "0.25rem 0" }}>
                    {run.skipped.map((s) => (
                      <li key={s.path}>
                        <code>{s.path}</code> - {s.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <p style={{ margin: "0.25rem 0" }}>Not run yet.</p>
          )}
        </div>
      )}
      {error && <ErrorMessage message={error} />}
    </section>
  );
}

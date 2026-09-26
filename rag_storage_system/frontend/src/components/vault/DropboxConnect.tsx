"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  disconnectDropbox,
  getDropboxStatus,
  listDropboxFolders,
  saveDropboxFolders,
  startDropboxConnect,
  type DropboxFolderList,
  type DropboxStatus,
} from "@/lib/api/dropbox";
import { ErrorMessage } from "@/components/ui/ErrorMessage";

const MAX_FOLDERS = 20;

function folderName(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

/**
 * The owner connects their own Dropbox and ticks the folders that become
 * library folders - no server settings (app/api/dropbox_api.py). After
 * folders are saved `onFoldersSaved` starts a sync; after a disconnect
 * `onDisconnected` refreshes the sync status.
 */
export function DropboxConnect({
  token,
  onFoldersSaved,
  onDisconnected,
}: {
  token: string;
  onFoldersSaved: () => void;
  onDisconnected: () => void;
}) {
  const [status, setStatus] = useState<DropboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isWorking, setIsWorking] = useState(false);

  // Folder picker
  const [isPicking, setIsPicking] = useState(false);
  const [listing, setListing] = useState<DropboxFolderList | null>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await getDropboxStatus(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the Dropbox connection.");
    }
  }, [token]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function run<T>(action: () => Promise<T>, failure: string): Promise<T | null> {
    setError(null);
    setIsWorking(true);
    try {
      return await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : failure);
      return null;
    } finally {
      setIsWorking(false);
    }
  }

  async function handleConnect() {
    const result = await run(() => startDropboxConnect(token), "Could not start the Dropbox connection.");
    // Dropbox's own sign-in page; it comes back to /vault/dropbox.
    if (result) window.location.assign(result.authorize_url);
  }

  async function openFolder(path: string) {
    const result = await run(() => listDropboxFolders(path, token), "Could not list that Dropbox folder.");
    if (result) setListing(result);
  }

  function startPicking() {
    setDraft(status?.folders.map((f) => f.path) ?? []);
    setIsPicking(true);
    void openFolder("");
  }

  function toggle(path: string) {
    setDraft((current) =>
      current.some((p) => p.toLowerCase() === path.toLowerCase())
        ? current.filter((p) => p.toLowerCase() !== path.toLowerCase())
        : [...current, path]
    );
  }

  async function saveFolders(paths: string[]) {
    const result = await run(() => saveDropboxFolders(paths, token), "Could not save the folders.");
    if (result) {
      setStatus(result);
      setIsPicking(false);
      setListing(null);
      if (result.folders.length > 0) onFoldersSaved();
    }
  }

  async function handleDisconnect() {
    const result = await run(() => disconnectDropbox(token), "Could not disconnect Dropbox.");
    if (result) {
      setStatus(result);
      setConfirmDisconnect(false);
      setIsPicking(false);
      onDisconnected();
    }
  }

  if (!status) return error ? <ErrorMessage message={error} /> : null;

  const box = {
    marginTop: "0.75rem",
    padding: "1rem 1.1rem",
    border: "1px solid #dde2e7",
  } as const;
  const muted = { fontSize: "0.85rem", color: "#5a6573", margin: "0.25rem 0" } as const;

  if (!status.connected || status.needs_reconnect) {
    return (
      <div style={box}>
        <strong>Dropbox</strong>
        {!status.available ? (
          <p style={muted}>
            Dropbox isn&apos;t set up on this server yet. A developer registers the AshiLegal Dropbox app once
            (settings <code>DROPBOX_APP_KEY</code> and <code>DROPBOX_APP_SECRET</code>, redirect URI{" "}
            <code>{status.redirect_uri}</code>). After that you connect your own Dropbox here.
          </p>
        ) : (
          <>
            <p style={muted}>
              {status.needs_reconnect
                ? "The saved Dropbox connection can't be used any more. Connect again - your chosen folders are kept if it's the same Dropbox."
                : "Connect your firm's Dropbox, then choose the folders to keep in the library. Files you add, change or delete in those folders follow automatically."}
            </p>
            <button type="submit" onClick={handleConnect} disabled={isWorking} style={{ marginTop: "0.5rem" }}>
              {isWorking ? "Opening Dropbox..." : status.needs_reconnect ? "Reconnect Dropbox" : "Connect Dropbox"}
            </button>
          </>
        )}
        {error && <ErrorMessage message={error} />}
      </div>
    );
  }

  const selectedLower = draft.map((p) => p.toLowerCase());
  const crumbs = listing ? listing.path.split("/").filter(Boolean) : [];

  return (
    <div style={box}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "0.75rem", flexWrap: "wrap" }}>
        <span>
          <strong>Dropbox connected</strong>
          <span style={{ color: "#5a6573", fontSize: "0.85rem" }}>
            {" "}
            · {status.account_name ?? ""} {status.account_email ? `(${status.account_email})` : ""}
          </span>
        </span>
        {confirmDisconnect ? (
          <span style={{ display: "flex", gap: "0.4rem", alignItems: "center", fontSize: "0.85rem" }}>
            Stop syncing? Library files stay.
            <button type="button" onClick={handleDisconnect} disabled={isWorking}>
              Yes, disconnect
            </button>
            <button type="button" onClick={() => setConfirmDisconnect(false)}>
              Cancel
            </button>
          </span>
        ) : (
          <button type="button" onClick={() => setConfirmDisconnect(true)} disabled={isWorking} style={{ fontSize: "0.85rem" }}>
            Disconnect
          </button>
        )}
      </div>

      {!isPicking && (
        <>
          <p style={{ ...muted, marginTop: "0.75rem", fontWeight: 600, color: "#1b2430" }}>Folders synced into the library</p>
          {status.folders.length === 0 ? (
            <p style={muted}>None yet. Choose the Dropbox folders that should become library folders.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: "0.25rem 0", padding: 0, display: "flex", flexDirection: "column", gap: "0.3rem" }}>
              {status.folders.map((folder) => (
                <li key={folder.path} style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem", fontSize: "0.9rem" }}>
                  <span>
                    📁 <code>{folder.path}</code> → library folder <strong>{folder.library_folder}</strong>
                  </span>
                  <button
                    type="button"
                    onClick={() => saveFolders(status.folders.map((f) => f.path).filter((p) => p !== folder.path))}
                    disabled={isWorking}
                    aria-label={`Stop syncing ${folder.path}`}
                    style={{ fontSize: "0.8rem", padding: "0.15rem 0.55rem" }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button type="button" onClick={startPicking} disabled={isWorking} style={{ marginTop: "0.5rem" }}>
            {status.folders.length === 0 ? "Choose folders" : "Change folders"}
          </button>
          {status.folders.length > 0 && (
            <p style={{ ...muted, marginTop: "0.5rem" }}>
              Removing a folder here takes its files out of the library on the next sync. Nothing in Dropbox is changed.
            </p>
          )}
        </>
      )}

      {isPicking && (
        <div style={{ marginTop: "0.75rem" }}>
          <nav aria-label="Dropbox folder" style={{ fontSize: "0.9rem", display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
            <button type="button" onClick={() => openFolder("")} disabled={isWorking} style={{ padding: "0.15rem 0.5rem" }}>
              Dropbox
            </button>
            {crumbs.map((crumb, index) => {
              const path = "/" + crumbs.slice(0, index + 1).join("/");
              return (
                <span key={path} style={{ display: "flex", gap: "0.25rem", alignItems: "center" }}>
                  ›
                  <button type="button" onClick={() => openFolder(path)} disabled={isWorking} style={{ padding: "0.15rem 0.5rem" }}>
                    {crumb}
                  </button>
                </span>
              );
            })}
          </nav>

          <ul style={{ listStyle: "none", margin: "0.6rem 0", padding: 0, maxHeight: 320, overflowY: "auto", border: "1px solid #dde2e7" }}>
            {!listing && <li style={{ padding: "0.6rem 0.8rem", ...muted }}>Loading folders...</li>}
            {listing && listing.folders.length === 0 && (
              <li style={{ padding: "0.6rem 0.8rem", ...muted }}>No folders inside this one.</li>
            )}
            {listing?.folders.map((folder) => {
              const checked = selectedLower.includes(folder.path.toLowerCase());
              const insideChosen = selectedLower.some((p) => folder.path.toLowerCase().startsWith(p + "/"));
              return (
                <li
                  key={folder.path}
                  style={{ display: "flex", alignItems: "center", gap: "0.6rem", padding: "0.45rem 0.8rem", borderBottom: "1px solid #eef1f4" }}
                >
                  <input
                    type="checkbox"
                    id={`dbx-${folder.path}`}
                    checked={checked || insideChosen}
                    disabled={insideChosen || isWorking || (!checked && draft.length >= MAX_FOLDERS)}
                    onChange={() => toggle(folder.path)}
                  />
                  <label htmlFor={`dbx-${folder.path}`} style={{ flex: 1, fontWeight: 400 }}>
                    📁 {folder.name}
                    {insideChosen && <span style={{ color: "#5a6573", fontSize: "0.8rem" }}> (included with its parent)</span>}
                  </label>
                  <button type="button" onClick={() => openFolder(folder.path)} disabled={isWorking} style={{ fontSize: "0.8rem", padding: "0.15rem 0.6rem" }}>
                    Open ›
                  </button>
                </li>
              );
            })}
          </ul>

          <p style={muted}>
            {draft.length === 0
              ? "Tick the folders to sync. Each one becomes a library folder; the folders inside it come along."
              : `Chosen: ${draft.map(folderName).join(", ")}`}
          </p>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button type="submit" onClick={() => saveFolders(draft)} disabled={isWorking}>
              {isWorking ? "Saving..." : "Save and sync"}
            </button>
            <button
              type="button"
              onClick={() => {
                setIsPicking(false);
                setListing(null);
              }}
              disabled={isWorking}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <ErrorMessage message={error} />}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import type { EndUserAccountInfo, InviteEndUsersResponse } from "@/lib/api/types";
import { deactivateEndUser, inviteEndUsers, listEndUsers, reactivateEndUser } from "@/lib/api/users";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

const STATUS_STYLES: Record<string, { background: string; color: string; label: string }> = {
  invited: { background: "#fff8e6", color: "#8a6116", label: "Invited - not signed up yet" },
  active: { background: "#eaf6ea", color: "#2e6b2e", label: "Active" },
  deactivated: { background: "#fdecea", color: "#c0392b", label: "Deactivated" },
};

function parseEmails(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter((e) => e.length > 0);
}

export function UserManager() {
  const { token, logout } = useAuth();

  const [users, setUsers] = useState<EndUserAccountInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState("");
  const [isInviting, setIsInviting] = useState(false);
  const [inviteResult, setInviteResult] = useState<InviteEndUsersResponse | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);

  const handleError = useCallback(
    (err: unknown, fallback: string, setter: (message: string) => void) => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setter(err instanceof ApiError ? err.message : fallback);
    },
    [logout]
  );

  const loadUsers = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (!token) throw new ApiError(401, "Session expired. Please log in again.");
      setUsers((await listEndUsers(token)).users);
    } catch (err) {
      handleError(err, "Could not load users.", setError);
    } finally {
      setIsLoading(false);
    }
  }, [token, handleError]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other admin page in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUsers();
  }, [loadUsers]);

  async function handleInvite(event: FormEvent) {
    event.preventDefault();
    const emails = parseEmails(draft);
    if (emails.length === 0 || !token) return;

    setActionError(null);
    setInviteResult(null);
    setIsInviting(true);
    try {
      const result = await inviteEndUsers(emails, token);
      setInviteResult(result);
      setDraft("");
      await loadUsers();
    } catch (err) {
      handleError(err, "Could not invite these users. Check the email addresses and try again.", setActionError);
    } finally {
      setIsInviting(false);
    }
  }

  async function handleToggle(user: EndUserAccountInfo) {
    if (!token) return;

    if (
      user.status !== "deactivated" &&
      !window.confirm(`Deactivate ${user.email}? They will be signed out immediately and unable to sign in.`)
    ) {
      return;
    }

    setActionError(null);
    setBusyUserId(user.id);
    try {
      if (user.status === "deactivated") {
        await reactivateEndUser(user.id, token);
      } else {
        await deactivateEndUser(user.id, token);
      }
      await loadUsers();
    } catch (err) {
      handleError(err, "Could not update this user.", setActionError);
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <section>
        <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Invite users</h3>
        <p style={{ color: "#666", fontSize: "0.85rem", margin: "0 0 0.5rem 0" }}>
          Enter one or more email addresses (one per line, or separated by commas). Each person gets an email with
          a link to create their account - only invited emails can sign up.
        </p>
        <form onSubmit={handleInvite} style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={4}
            placeholder={"rahul.ashilegal@gmail.com\npriya.ashilegal@gmail.com"}
            disabled={isInviting}
            style={{ width: "100%", fontFamily: "inherit" }}
          />
          <button type="submit" disabled={isInviting || parseEmails(draft).length === 0} style={{ alignSelf: "flex-start" }}>
            {isInviting ? "Inviting..." : `Invite ${parseEmails(draft).length || ""} user${parseEmails(draft).length === 1 ? "" : "s"}`}
          </button>
        </form>

        {inviteResult && (
          <div style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
            {inviteResult.invited.length > 0 && (
              <p style={{ color: "#2e6b2e", margin: "0 0 0.25rem 0" }}>
                Invited {inviteResult.invited.length}: {inviteResult.invited.map((u) => u.email).join(", ")}
              </p>
            )}
            {inviteResult.skipped.map((s) => (
              <p key={s.email} style={{ color: "#8a6116", margin: 0 }}>
                Skipped {s.email} - {s.reason}
              </p>
            ))}
          </div>
        )}
        {actionError && (
          <div style={{ marginTop: "0.75rem" }}>
            <ErrorMessage message={actionError} />
          </div>
        )}
      </section>

      <section>
        <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>All users ({users.length})</h3>
        {isLoading && <LoadingSpinner label="Loading users..." />}
        {error && <ErrorMessage message={error} />}
        {!isLoading && !error && users.length === 0 && (
          <p style={{ color: "#777", fontSize: "0.9rem" }}>No users invited yet.</p>
        )}
        {!isLoading && !error && users.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
                <th style={{ padding: "0.4rem" }}>Email</th>
                <th style={{ padding: "0.4rem" }}>Status</th>
                <th style={{ padding: "0.4rem" }}>Signed up</th>
                <th style={{ padding: "0.4rem" }} />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const style = STATUS_STYLES[user.status] ?? { background: "#eee", color: "#333", label: user.status };
                return (
                  <tr key={user.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "0.4rem" }}>{user.email}</td>
                    <td style={{ padding: "0.4rem" }}>
                      <span
                        style={{
                          background: style.background,
                          color: style.color,
                          borderRadius: 12,
                          padding: "0.1rem 0.5rem",
                          fontSize: "0.8rem",
                        }}
                      >
                        {style.label}
                      </span>
                    </td>
                    <td style={{ padding: "0.4rem", color: "#666" }}>
                      {user.activated_at ? new Date(user.activated_at).toLocaleDateString() : "-"}
                    </td>
                    <td style={{ padding: "0.4rem", textAlign: "right" }}>
                      <button type="button" onClick={() => handleToggle(user)} disabled={busyUserId === user.id}>
                        {busyUserId === user.id ? "Saving..." : user.status === "deactivated" ? "Reactivate" : "Deactivate"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

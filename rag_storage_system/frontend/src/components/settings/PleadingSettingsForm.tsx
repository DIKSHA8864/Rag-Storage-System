"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { getPleadingSettings, savePleadingSettings } from "@/lib/api/pleadings";
import type { PleadingSettings } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

const EMPTY: PleadingSettings = {
  attorney_name: "",
  bar_number: "",
  firm_name: "",
  address: "",
  phone: "",
  email: "",
  attorney_for: "",
  court_name: "",
  county: "",
};

const FIELDS: { key: keyof PleadingSettings; label: string; hint?: string; multiline?: boolean }[] = [
  { key: "attorney_name", label: "Attorney name" },
  { key: "bar_number", label: "State Bar number" },
  { key: "firm_name", label: "Firm name" },
  { key: "address", label: "Address", multiline: true },
  { key: "phone", label: "Telephone" },
  { key: "email", label: "Email" },
  { key: "attorney_for", label: "Attorney for", hint: 'e.g. "Plaintiff" or "Plaintiff JOHN DOE"' },
  { key: "court_name", label: "Court", hint: "Blank = SUPERIOR COURT OF THE STATE OF CALIFORNIA" },
  { key: "county", label: "Default county", hint: "Can be changed for each complaint" },
];

/** The attorney block and court printed at the top of every generated pleading. Blank fields stay [BRACKETED]. */
export function PleadingSettingsForm() {
  const { token, logout } = useAuth();
  const [values, setValues] = useState<PleadingSettings>(EMPTY);
  const [lastSaved, setLastSaved] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const failure = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : fallback);
    },
    [logout]
  );

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (!token) throw new ApiError(401, "Session expired. Please log in again.");
      const settings = await getPleadingSettings(token);
      const { updated_at, updated_by, ...rest } = settings;
      setValues(rest);
      setLastSaved(
        updated_at ? `Last saved ${new Date(updated_at).toLocaleString()}${updated_by ? ` by ${updated_by}` : ""}.` : "Not set yet."
      );
    } catch (err) {
      failure(err, "Could not load the pleading details.");
    } finally {
      setIsLoading(false);
    }
  }, [token, failure]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await savePleadingSettings(values, token);
      setLastSaved(`Last saved ${new Date(saved.updated_at ?? "").toLocaleString()}${saved.updated_by ? ` by ${saved.updated_by}` : ""}.`);
      setMessage("Saved - used on the next complaint you generate.");
    } catch (err) {
      failure(err, "Could not save the pleading details.");
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) return <LoadingSpinner label="Loading pleading details..." />;

  return (
    <form onSubmit={handleSave} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem 1rem" }}>
      {FIELDS.map((field) => (
        <label key={field.key} style={{ display: "flex", flexDirection: "column", gap: "0.2rem", fontSize: "0.85rem" }}>
          {field.label}
          {field.multiline ? (
            <textarea
              rows={2}
              aria-label={field.label}
              value={values[field.key]}
              onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))}
            />
          ) : (
            <input aria-label={field.label} value={values[field.key]} onChange={(e) => setValues((v) => ({ ...v, [field.key]: e.target.value }))} />
          )}
          {field.hint && <span style={{ fontSize: "0.75rem", color: "#777" }}>{field.hint}</span>}
        </label>
      ))}
      <div style={{ gridColumn: "1 / -1" }}>
        {error && <ErrorMessage message={error} />}
        {message && <p style={{ color: "#2e7d32", fontSize: "0.85rem" }}>{message}</p>}
        <button type="submit" disabled={isSaving}>
          {isSaving ? "Saving..." : "Save pleading details"}
        </button>
        <span style={{ marginLeft: "0.75rem", fontSize: "0.8rem", color: "#777" }}>{lastSaved}</span>
      </div>
    </form>
  );
}

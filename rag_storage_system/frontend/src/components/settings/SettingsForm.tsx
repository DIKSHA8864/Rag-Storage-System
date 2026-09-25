"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { getDisclaimer, getRetrievalSettings, saveDisclaimer, saveRetrievalSettings } from "@/lib/api/settings";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

function lastSaved(updatedAt: string | null, updatedBy: string | null): string {
  if (!updatedAt) return "Using the built-in defaults.";
  return `Last saved ${new Date(updatedAt).toLocaleString()}${updatedBy ? ` by ${updatedBy}` : ""}.`;
}

const fieldStyle = { display: "flex", flexDirection: "column" as const, gap: "0.25rem", maxWidth: 360 };
const hintStyle = { fontSize: "0.8rem", color: "#777" };

export function SettingsForm() {
  const { token, logout } = useAuth();

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [topK, setTopK] = useState("5");
  const [threshold, setThreshold] = useState("0.3");
  const [minChunks, setMinChunks] = useState("1");
  const [retrievalSaved, setRetrievalSaved] = useState("");
  const [retrievalMessage, setRetrievalMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [isSavingRetrieval, setIsSavingRetrieval] = useState(false);

  const [disclaimer, setDisclaimer] = useState("");
  const [disclaimerSaved, setDisclaimerSaved] = useState("");
  const [disclaimerMessage, setDisclaimerMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [isSavingDisclaimer, setIsSavingDisclaimer] = useState(false);

  const failureText = useCallback(
    (err: unknown, fallback: string): string | null => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return null;
      }
      return err instanceof ApiError ? err.message : fallback;
    },
    [logout]
  );

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      if (!token) throw new ApiError(401, "Session expired. Please log in again.");
      const [settings, current] = await Promise.all([getRetrievalSettings(token), getDisclaimer(token)]);
      setTopK(String(settings.top_k));
      setThreshold(String(settings.score_threshold));
      setMinChunks(String(settings.min_chunks));
      setRetrievalSaved(lastSaved(settings.updated_at, settings.updated_by));
      setDisclaimer(current.text);
      setDisclaimerSaved(lastSaved(current.updated_at, current.updated_by));
    } catch (err) {
      const text = failureText(err, "Could not load settings.");
      if (text) setLoadError(text);
    } finally {
      setIsLoading(false);
    }
  }, [token, failureText]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function handleSaveRetrieval(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setRetrievalMessage(null);
    const values = { top_k: Number(topK), score_threshold: Number(threshold), min_chunks: Number(minChunks) };
    if (!Number.isInteger(values.top_k) || values.top_k < 1 || values.top_k > 50) {
      setRetrievalMessage({ ok: false, text: "Sources per answer must be a whole number from 1 to 50." });
      return;
    }
    if (!(values.score_threshold >= 0 && values.score_threshold <= 1)) {
      setRetrievalMessage({ ok: false, text: "Minimum relevance must be between 0 and 1." });
      return;
    }
    if (!Number.isInteger(values.min_chunks) || values.min_chunks < 0 || values.min_chunks > 50) {
      setRetrievalMessage({ ok: false, text: "Minimum sources must be a whole number from 0 to 50." });
      return;
    }
    setIsSavingRetrieval(true);
    try {
      const saved = await saveRetrievalSettings(values, token);
      setRetrievalSaved(lastSaved(saved.updated_at, saved.updated_by));
      setRetrievalMessage({ ok: true, text: "Saved - applies to the next question." });
    } catch (err) {
      const text = failureText(err, "Could not save retrieval settings.");
      if (text) setRetrievalMessage({ ok: false, text });
    } finally {
      setIsSavingRetrieval(false);
    }
  }

  async function handleSaveDisclaimer(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setDisclaimerMessage(null);
    if (disclaimer.trim() === "") {
      setDisclaimerMessage({ ok: false, text: "The disclaimer can't be empty." });
      return;
    }
    setIsSavingDisclaimer(true);
    try {
      const saved = await saveDisclaimer(disclaimer.trim(), token);
      setDisclaimerSaved(lastSaved(saved.updated_at, saved.updated_by));
      setDisclaimerMessage({ ok: true, text: "Saved - appears on the next exported file." });
    } catch (err) {
      const text = failureText(err, "Could not save the disclaimer.");
      if (text) setDisclaimerMessage({ ok: false, text });
    } finally {
      setIsSavingDisclaimer(false);
    }
  }

  if (isLoading) return <LoadingSpinner label="Loading settings..." />;
  if (loadError) return <ErrorMessage message={loadError} />;

  const message = (m: { ok: boolean; text: string } | null) =>
    m && <p style={{ fontSize: "0.85rem", color: m.ok ? "#2e6b2e" : "#c0392b", margin: 0 }}>{m.text}</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
      <section>
        <h2 style={{ fontSize: "1.1rem" }}>Answer sources</h2>
        <p style={{ color: "#666", fontSize: "0.9rem" }}>
          How the library is searched for every question (Research, Matters, and Ask). Higher &quot;minimum
          relevance&quot; means fewer, stricter sources and more &quot;No authority&quot; answers.
        </p>
        <form onSubmit={handleSaveRetrieval} style={{ display: "flex", flexDirection: "column", gap: "0.9rem" }}>
          <label style={fieldStyle}>
            Sources per answer
            <input type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(e.target.value)} />
            <span style={hintStyle}>How many library passages are considered (1-50). Default 5.</span>
          </label>
          <label style={fieldStyle}>
            Minimum relevance
            <input type="number" min={0} max={1} step={0.01} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
            <span style={hintStyle}>0 to 1. Passages scoring below this are ignored. Default 0.3.</span>
          </label>
          <label style={fieldStyle}>
            Minimum sources to answer
            <input type="number" min={0} max={50} value={minChunks} onChange={(e) => setMinChunks(e.target.value)} />
            <span style={hintStyle}>
              Fewer relevant passages than this gives &quot;No authority on this point&quot;. Default 1.
            </span>
          </label>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <button type="submit" disabled={isSavingRetrieval} aria-busy={isSavingRetrieval}>
              {isSavingRetrieval ? "Saving..." : "Save"}
            </button>
            {message(retrievalMessage)}
          </div>
          <p style={hintStyle}>{retrievalSaved}</p>
        </form>
      </section>

      <section>
        <h2 style={{ fontSize: "1.1rem" }}>Disclaimer</h2>
        <p style={{ color: "#666", fontSize: "0.9rem" }}>
          Printed on every exported research memo, intake report, and draft complaint.
        </p>
        <form onSubmit={handleSaveDisclaimer} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <textarea
            value={disclaimer}
            onChange={(e) => setDisclaimer(e.target.value)}
            rows={5}
            maxLength={5000}
            aria-label="Disclaimer text"
            style={{ width: "100%", resize: "vertical" }}
          />
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <button type="submit" disabled={isSavingDisclaimer} aria-busy={isSavingDisclaimer}>
              {isSavingDisclaimer ? "Saving..." : "Save disclaimer"}
            </button>
            {message(disclaimerMessage)}
          </div>
          <p style={hintStyle}>{disclaimerSaved}</p>
        </form>
      </section>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { getIntakeChecklist, resetIntakeChecklist, saveIntakeChecklist } from "@/lib/api/intakeChecklist";
import type { IntakeChecklistItem } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

const hintStyle = { fontSize: "0.8rem", color: "#777" };
const textAreaStyle = { width: "100%", resize: "vertical" as const, fontFamily: "inherit" };

/**
 * The screening questions every client is asked (the "ancillary sweep"),
 * after their story and follow-ups. Required Blueprint topics can be
 * reworded but not switched off; everything else can be switched off,
 * reordered, or added. The server re-checks all of it.
 */
export function ChecklistEditor() {
  const { token, logout } = useAuth();

  const [items, setItems] = useState<IntakeChecklistItem[]>([]);
  const [customized, setCustomized] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  const [newKey, setNewKey] = useState("");
  const [newEn, setNewEn] = useState("");
  const [newEs, setNewEs] = useState("");

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
      const checklist = await getIntakeChecklist(token);
      setItems(checklist.items);
      setCustomized(checklist.customized);
      setIsDirty(false);
    } catch (err) {
      const text = failureText(err, "Could not load the checklist.");
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

  function update(index: number, change: Partial<IntakeChecklistItem>) {
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...change } : item)));
    setIsDirty(true);
    setMessage(null);
  }

  function move(index: number, delta: number) {
    setItems((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setIsDirty(true);
    setMessage(null);
  }

  function remove(index: number) {
    setItems((prev) => prev.filter((_, i) => i !== index));
    setIsDirty(true);
    setMessage(null);
  }

  function addQuestion() {
    const key = newKey.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    if (!key || !newEn.trim() || !newEs.trim()) {
      setMessage({ ok: false, text: "A new question needs a short name, the English question, and the Spanish question." });
      return;
    }
    if (items.some((item) => item.key === key)) {
      setMessage({ ok: false, text: `There is already a question named "${key}".` });
      return;
    }
    setItems((prev) => [...prev, { key, prompt_en: newEn.trim(), prompt_es: newEs.trim(), is_active: true, required: false }]);
    setNewKey("");
    setNewEn("");
    setNewEs("");
    setIsDirty(true);
    setMessage(null);
  }

  async function handleSave() {
    if (!token) return;
    setIsSaving(true);
    setMessage(null);
    try {
      const saved = await saveIntakeChecklist(token, items);
      setItems(saved.items);
      setCustomized(saved.customized);
      setIsDirty(false);
      setMessage({ ok: true, text: "Saved. New interviews use this checklist; interviews already started keep theirs." });
    } catch (err) {
      const text = failureText(err, "Could not save the checklist.");
      if (text) setMessage({ ok: false, text });
    } finally {
      setIsSaving(false);
    }
  }

  async function handleReset() {
    if (!token) return;
    if (!window.confirm("Replace your checklist with the built-in default questions?")) return;
    setIsSaving(true);
    setMessage(null);
    try {
      const reset = await resetIntakeChecklist(token);
      setItems(reset.items);
      setCustomized(reset.customized);
      setIsDirty(false);
      setMessage({ ok: true, text: "Back to the built-in default checklist." });
    } catch (err) {
      const text = failureText(err, "Could not reset the checklist.");
      if (text) setMessage({ ok: false, text });
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) return <LoadingSpinner label="Loading checklist..." />;
  if (loadError) {
    return (
      <div>
        <ErrorMessage message={loadError} />
        <button type="button" onClick={load} style={{ marginTop: "0.75rem" }}>
          Retry
        </button>
      </div>
    );
  }

  const activeCount = items.filter((item) => item.is_active).length;

  return (
    <div>
      <p style={hintStyle}>
        {customized ? "Your organization's checklist." : "The built-in default checklist (not changed yet)."} {activeCount}{" "}
        of {items.length} questions are asked.
      </p>

      <ol style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        {items.map((item, index) => (
          <li
            key={item.key}
            style={{
              border: "1px solid #e0e0e0",
              borderRadius: 6,
              padding: "0.75rem",
              background: item.is_active ? "#fff" : "#f7f7f7",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
              <strong style={{ fontSize: "0.85rem" }}>
                {index + 1}. {item.key}
                {item.required && (
                  <span style={{ marginLeft: "0.5rem", fontWeight: 400, color: "#1a5fb4" }}>required topic</span>
                )}
              </strong>
              <span style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                <label style={{ fontSize: "0.8rem" }} title={item.required ? "Required topics are always asked." : undefined}>
                  <input
                    type="checkbox"
                    checked={item.is_active}
                    disabled={item.required}
                    onChange={(e) => update(index, { is_active: e.target.checked })}
                  />{" "}
                  Ask
                </label>
                <button type="button" onClick={() => move(index, -1)} disabled={index === 0} aria-label="Move up">
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => move(index, 1)}
                  disabled={index === items.length - 1}
                  aria-label="Move down"
                >
                  ↓
                </button>
                {!item.required && (
                  <button type="button" onClick={() => remove(index)} aria-label={`Remove ${item.key}`}>
                    Remove
                  </button>
                )}
              </span>
            </div>
            <label style={{ display: "block", marginTop: "0.5rem", fontSize: "0.8rem" }}>
              English
              <textarea
                rows={2}
                value={item.prompt_en}
                onChange={(e) => update(index, { prompt_en: e.target.value })}
                style={textAreaStyle}
              />
            </label>
            <label style={{ display: "block", marginTop: "0.35rem", fontSize: "0.8rem" }}>
              Spanish
              <textarea
                rows={2}
                value={item.prompt_es}
                onChange={(e) => update(index, { prompt_es: e.target.value })}
                style={textAreaStyle}
              />
            </label>
          </li>
        ))}
      </ol>

      <fieldset style={{ marginTop: "1rem", border: "1px dashed #ccc", borderRadius: 6, padding: "0.75rem" }}>
        <legend style={{ fontSize: "0.85rem" }}>Add a question</legend>
        <label style={{ display: "block", fontSize: "0.8rem" }}>
          Short name (used in reports, e.g. &quot;tips&quot;)
          <input value={newKey} onChange={(e) => setNewKey(e.target.value)} style={{ width: "100%" }} />
        </label>
        <label style={{ display: "block", marginTop: "0.35rem", fontSize: "0.8rem" }}>
          English question
          <textarea rows={2} value={newEn} onChange={(e) => setNewEn(e.target.value)} style={textAreaStyle} />
        </label>
        <label style={{ display: "block", marginTop: "0.35rem", fontSize: "0.8rem" }}>
          Spanish question
          <textarea rows={2} value={newEs} onChange={(e) => setNewEs(e.target.value)} style={textAreaStyle} />
        </label>
        <button type="button" onClick={addQuestion} style={{ marginTop: "0.5rem" }}>
          Add to checklist
        </button>
      </fieldset>

      {message && (
        <p role="status" style={{ color: message.ok ? "#2e7d32" : "#b3261e", fontSize: "0.9rem" }}>
          {message.text}
        </p>
      )}

      <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
        <button type="button" onClick={handleSave} disabled={isSaving || !isDirty}>
          {isSaving ? "Saving..." : "Save checklist"}
        </button>
        <button type="button" onClick={handleReset} disabled={isSaving || !customized}>
          Reset to default
        </button>
      </div>
    </div>
  );
}

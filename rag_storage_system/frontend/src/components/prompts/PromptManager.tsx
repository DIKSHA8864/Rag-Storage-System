"use client";

import { useCallback, useEffect, useState } from "react";

import { activatePromptVersion, createPromptVersion, listPromptVersions } from "@/lib/api/prompts";
import { ApiError } from "@/lib/api/client";
import type { PromptVersionInfo } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * The known, registered system prompt slots - app/analysis/claude_narrative.py
 * and app/analysis/answer_generation.py's get_active_prompt() calls are the
 * entire real prompt registry today. Not invented labels: these are the
 * only two names the backend actually recognizes.
 */
const PROMPT_SLOTS = [
  { name: "narrative_system_prompt", label: "Client Report Narrative (Claude)" },
  { name: "answer_system_prompt", label: "Research Answer Generation (Claude)" },
];

export function PromptManager() {
  const { token, logout } = useAuth();
  const [selectedName, setSelectedName] = useState(PROMPT_SLOTS[0].name);
  const [versions, setVersions] = useState<PromptVersionInfo[]>([]);
  const [draftText, setDraftText] = useState("");

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [activatingVersion, setActivatingVersion] = useState<number | null>(null);

  const loadVersions = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const response = await listPromptVersions(selectedName, token);
      setVersions(response.versions);
      const active = response.versions.find((v) => v.is_active);
      setDraftText(active ? active.text : "");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load this prompt's versions.");
    } finally {
      setIsLoading(false);
    }
  }, [selectedName, token, logout]);

  useEffect(() => {
    // Fetching whenever the selected prompt changes is exactly what
    // this effect is for - same legitimate case as every other
    // page-load fetch in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadVersions();
  }, [loadVersions]);

  async function handleSave() {
    if (!draftText.trim()) {
      setSaveError("Prompt text cannot be empty.");
      return;
    }

    setSaveError(null);
    setIsSaving(true);
    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      await createPromptVersion(selectedName, { text: draftText }, token);
      await loadVersions();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSaveError(err instanceof ApiError ? err.message : "Could not save this prompt version.");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleActivate(version: number) {
    setSaveError(null);
    setActivatingVersion(version);
    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      await activatePromptVersion(selectedName, version, token);
      await loadVersions();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setSaveError(err instanceof ApiError ? err.message : "Could not activate this version.");
    } finally {
      setActivatingVersion(null);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem", maxWidth: 720 }}>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        {PROMPT_SLOTS.map((slot) => (
          <button
            key={slot.name}
            type="button"
            onClick={() => setSelectedName(slot.name)}
            disabled={slot.name === selectedName}
            style={{ fontWeight: slot.name === selectedName ? 600 : 400 }}
          >
            {slot.label}
          </button>
        ))}
      </div>

      {isLoading && <LoadingSpinner label="Loading prompt versions..." />}
      {error && <ErrorMessage message={error} />}

      {!isLoading && !error && (
        <>
          <div>
            <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Edit and save a new version</h3>
            {saveError && <ErrorMessage message={saveError} />}
            <textarea
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              rows={10}
              style={{ width: "100%", fontFamily: "monospace", fontSize: "0.85rem" }}
            />
            <button type="button" onClick={handleSave} disabled={isSaving} style={{ marginTop: "0.5rem" }}>
              {isSaving ? "Saving..." : "Save as new active version"}
            </button>
          </div>

          <div>
            <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Version history</h3>
            {versions.length === 0 && (
              <p style={{ color: "#777", fontSize: "0.85rem" }}>
                No saved versions yet - the built-in default prompt is in effect until one is saved here.
              </p>
            )}
            <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {versions.map((v) => (
                <li
                  key={v.version}
                  style={{
                    border: "1px solid #e5e5e5",
                    borderRadius: 4,
                    padding: "0.5rem 0.75rem",
                    background: v.is_active ? "#eaf6ea" : "#fff",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "0.85rem" }}>
                      v{v.version} {v.is_active && <strong>(active)</strong>} - {v.created_at}
                      {v.created_by && ` - ${v.created_by}`}
                    </span>
                    {!v.is_active && (
                      <button
                        type="button"
                        onClick={() => handleActivate(v.version)}
                        disabled={activatingVersion === v.version}
                      >
                        {activatingVersion === v.version ? "Activating..." : "Activate"}
                      </button>
                    )}
                  </div>
                  <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem", margin: "0.5rem 0 0 0" }}>{v.text}</pre>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

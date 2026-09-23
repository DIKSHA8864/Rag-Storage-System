"use client";

import { useCallback, useEffect, useState } from "react";

import { generateComplaint, listCausesOfAction, listSessionComplaints, downloadComplaint } from "@/lib/api/complaints";
import { ApiError } from "@/lib/api/client";
import type { CauseOfActionInfo, ComplaintDraftResponse, ComplaintInfo } from "@/lib/api/types";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { CauseOfActionForm } from "./CauseOfActionForm";
import { ComplaintDraftPreview } from "./ComplaintDraftPreview";

interface ComplaintGeneratorProps {
  sessionId: number;
  token: string;
  onAuthFailure: () => void;
}

/**
 * The real Complaint Generator - selects curated causes of action,
 * calls app/api/complaint_api.py's generate endpoint (which reuses
 * app/complaint/builder.py's keyword-overlap element matching, never
 * an LLM), previews the resulting sections, and offers the
 * ready-to-file DOCX download plus past drafts for this session.
 */
export function ComplaintGenerator({ sessionId, token, onAuthFailure }: ComplaintGeneratorProps) {
  const [causesOfAction, setCausesOfAction] = useState<CauseOfActionInfo[]>([]);
  const [pastComplaints, setPastComplaints] = useState<ComplaintInfo[]>([]);
  const [selectedCauseIds, setSelectedCauseIds] = useState<number[]>([]);
  const [draft, setDraft] = useState<ComplaintDraftResponse | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [showCauseForm, setShowCauseForm] = useState(false);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);

    try {
      const [causesResponse, complaintsResponse] = await Promise.all([
        listCausesOfAction(token),
        listSessionComplaints(sessionId, token),
      ]);
      setCausesOfAction(causesResponse.causes_of_action);
      setPastComplaints(complaintsResponse.complaints);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setLoadError(err instanceof ApiError ? err.message : "Could not load the complaint generator.");
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, token, onAuthFailure]);

  useEffect(() => {
    // Fetching on mount is exactly what this effect is for - same
    // legitimate case as every other page-load fetch in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData();
  }, [loadData]);

  function toggleCause(causeId: number) {
    setSelectedCauseIds((current) =>
      current.includes(causeId) ? current.filter((id) => id !== causeId) : [...current, causeId]
    );
  }

  async function handleGenerate() {
    if (selectedCauseIds.length === 0) {
      setGenerateError("Select at least one cause of action.");
      return;
    }

    setGenerateError(null);
    setIsGenerating(true);
    try {
      const response = await generateComplaint(sessionId, { cause_of_action_ids: selectedCauseIds, format: "docx" }, token);
      setDraft(response);
      const complaintsResponse = await listSessionComplaints(sessionId, token);
      setPastComplaints(complaintsResponse.complaints);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setGenerateError(err instanceof ApiError ? err.message : "Could not generate the draft complaint.");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDownload(complaintId: number) {
    try {
      const blob = await downloadComplaint(complaintId, token);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `complaint_${complaintId}.docx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setGenerateError(err instanceof ApiError ? err.message : "Could not download this draft.");
    }
  }

  function handleCauseCreated(cause: CauseOfActionInfo) {
    setCausesOfAction((current) => [...current, cause]);
    setShowCauseForm(false);
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading complaint generator..." />;
  }

  if (loadError) {
    return <ErrorMessage message={loadError} />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div>
        <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Causes of action</h3>

        {causesOfAction.length === 0 && <p style={{ color: "#777", fontSize: "0.85rem" }}>No causes of action curated yet.</p>}

        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          {causesOfAction.map((cause) => (
            <label key={cause.id} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem" }}>
              <input
                type="checkbox"
                checked={selectedCauseIds.includes(cause.id)}
                onChange={() => toggleCause(cause.id)}
              />
              {cause.name} <span style={{ color: "#999" }}>({cause.category})</span>
            </label>
          ))}
        </div>

        <button type="button" onClick={() => setShowCauseForm((v) => !v)} style={{ marginTop: "0.5rem" }}>
          {showCauseForm ? "Cancel" : "Curate a new cause of action"}
        </button>

        {showCauseForm && (
          <div style={{ marginTop: "0.5rem" }}>
            <CauseOfActionForm token={token} onCreated={handleCauseCreated} onAuthFailure={onAuthFailure} />
          </div>
        )}
      </div>

      <div>
        {generateError && <ErrorMessage message={generateError} />}
        <button type="button" onClick={handleGenerate} disabled={isGenerating || selectedCauseIds.length === 0}>
          {isGenerating ? "Generating..." : "Generate draft complaint"}
        </button>
      </div>

      {draft && (
        <div>
          <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Draft preview</h3>
          <p style={{ fontSize: "0.8rem", color: "#a15c00" }}>
            This is a DRAFT. Bracketed placeholders must be completed and an attorney must review it before filing.
          </p>
          <ComplaintDraftPreview sections={draft.sections} />
          <button type="button" onClick={() => handleDownload(draft.id)} style={{ marginTop: "0.5rem" }}>
            Download DOCX
          </button>
        </div>
      )}

      {pastComplaints.length > 0 && (
        <div>
          <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>Past drafts</h3>
          <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {pastComplaints.map((complaint) => (
              <li key={complaint.id} style={{ fontSize: "0.85rem", display: "flex", justifyContent: "space-between" }}>
                <span>Draft #{complaint.id} - {complaint.created_at}</span>
                <button type="button" onClick={() => handleDownload(complaint.id)}>
                  Download
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

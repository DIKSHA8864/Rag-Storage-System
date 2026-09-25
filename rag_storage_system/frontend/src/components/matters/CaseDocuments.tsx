"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import {
  deleteMatterDocument,
  downloadMatterDocument,
  listMatterDocuments,
  reindexMatterDocument,
  uploadMatterDocument,
} from "@/lib/api/matterDocuments";
import type { MatterDocumentInfo } from "@/lib/api/types";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

interface CaseDocumentsProps {
  matterId: number;
  token: string;
  onAuthFailure: () => void;
}

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  queued: { label: "Indexing...", color: "#8a6116" },
  indexed: { label: "Searchable", color: "#2e7d32" },
  failed: { label: "Failed", color: "#b3261e" },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * The attorney's own documents for this case - pleadings, orders,
 * motions, correspondence. Each upload is virus-scanned and indexed into
 * this matter only, so this matter's research, reports and complaint
 * drafts can cite it; the firm's library and other matters never see it.
 */
export function CaseDocuments({ matterId, token, onAuthFailure }: CaseDocumentsProps) {
  const [documents, setDocuments] = useState<MatterDocumentInfo[]>([]);
  const [docTypes, setDocTypes] = useState<string[]>([]);
  const [docType, setDocType] = useState("pleading");
  const [file, setFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isMounted = useRef(true);

  const failure = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        onAuthFailure();
        return;
      }
      setError(err instanceof ApiError ? err.message : fallback);
    },
    [onAuthFailure]
  );

  const refresh = useCallback(async (): Promise<MatterDocumentInfo[]> => {
    const response = await listMatterDocuments(matterId, token);
    setDocuments(response.documents);
    setDocTypes(response.doc_types);
    return response.documents;
  }, [matterId, token]);

  // Indexing runs in the background worker - check back until nothing is queued (about a minute at most).
  const followIndexing = useCallback(async () => {
    for (let attempt = 0; attempt < 20 && isMounted.current; attempt += 1) {
      await sleep(3000);
      try {
        const current = await refresh();
        if (!current.some((doc) => doc.status === "queued")) return;
      } catch {
        return;
      }
    }
  }, [refresh]);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const current = await refresh();
      if (current.some((doc) => doc.status === "queued")) void followIndexing();
    } catch (err) {
      failure(err, "Could not load the case documents.");
    } finally {
      setIsLoading(false);
    }
  }, [refresh, followIndexing, failure]);

  useEffect(() => {
    isMounted.current = true;
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    return () => {
      isMounted.current = false;
    };
  }, [load]);

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setIsUploading(true);
    setError(null);
    try {
      const uploaded = await uploadMatterDocument(matterId, file, docType, token);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      await refresh();
      if (uploaded.status === "queued") void followIndexing();
    } catch (err) {
      failure(err, "Could not upload this document.");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleDownload(doc: MatterDocumentInfo) {
    try {
      const blob = await downloadMatterDocument(matterId, doc.id, token);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = doc.original_filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      failure(err, "Could not download this document.");
    }
  }

  async function handleReindex(doc: MatterDocumentInfo) {
    setError(null);
    try {
      await reindexMatterDocument(matterId, doc.id, token);
      await refresh();
      void followIndexing();
    } catch (err) {
      failure(err, "Could not re-index this document.");
    }
  }

  async function handleDelete(doc: MatterDocumentInfo) {
    if (!window.confirm(`Delete "${doc.original_filename}" from this case? It will no longer be searchable.`)) return;
    setError(null);
    try {
      await deleteMatterDocument(matterId, doc.id, token);
      await refresh();
    } catch (err) {
      failure(err, "Could not delete this document.");
    }
  }

  if (isLoading) return <LoadingSpinner label="Loading case documents..." />;

  return (
    <div>
      <form onSubmit={handleUpload} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <label style={{ fontSize: "0.85rem" }}>
          Type{" "}
          <select value={docType} onChange={(e) => setDocType(e.target.value)} disabled={isUploading}>
            {docTypes.map((type) => (
              <option key={type} value={type}>
                {type.charAt(0).toUpperCase() + type.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          aria-label="Case document file"
          disabled={isUploading}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" disabled={!file || isUploading}>
          {isUploading ? "Uploading..." : "Upload"}
        </button>
      </form>
      <p style={{ fontSize: "0.8rem", color: "#777", margin: "0.35rem 0 0.75rem 0" }}>
        PDF, DOCX or TXT. Only this matter&apos;s research, reports and drafts can cite these - never the firm
        library or another matter.
      </p>

      {error && <ErrorMessage message={error} />}

      {documents.length === 0 ? (
        <p style={{ color: "#777" }}>No case documents yet.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #e0e0e0" }}>
              <th style={{ padding: "0.35rem" }}>Document</th>
              <th style={{ padding: "0.35rem" }}>Type</th>
              <th style={{ padding: "0.35rem" }}>Status</th>
              <th style={{ padding: "0.35rem" }} />
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => {
              const status = STATUS_STYLE[doc.status] ?? { label: doc.status, color: "#555" };
              return (
                <tr key={doc.id} style={{ borderBottom: "1px solid #f0f0f0", verticalAlign: "top" }}>
                  <td style={{ padding: "0.35rem" }}>
                    {doc.original_filename}
                    <div style={{ color: "#777", fontSize: "0.75rem" }}>
                      {formatSize(doc.size)} - {new Date(doc.created_at).toLocaleDateString()}
                      {doc.uploaded_by ? ` - ${doc.uploaded_by}` : ""}
                    </div>
                  </td>
                  <td style={{ padding: "0.35rem" }}>{doc.doc_type}</td>
                  <td style={{ padding: "0.35rem", color: status.color }}>
                    {status.label}
                    {doc.status === "indexed" && ` (${doc.chunk_count} ${doc.chunk_count === 1 ? "passage" : "passages"})`}
                    {doc.error && <div style={{ fontSize: "0.75rem" }}>{doc.error}</div>}
                  </td>
                  <td style={{ padding: "0.35rem", whiteSpace: "nowrap" }}>
                    <button type="button" onClick={() => handleDownload(doc)}>
                      Download
                    </button>{" "}
                    {doc.status === "failed" && (
                      <>
                        <button type="button" onClick={() => handleReindex(doc)}>
                          Retry
                        </button>{" "}
                      </>
                    )}
                    <button type="button" onClick={() => handleDelete(doc)} aria-label={`Delete ${doc.original_filename}`}>
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

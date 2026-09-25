"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";
import { deleteTemplate, downloadTemplate, listTemplates, uploadTemplate } from "@/lib/api/pleadings";
import type { DocumentTemplateInfo } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

/**
 * The firm's own Word templates for complaints. A template is any .docx
 * with {{placeholders}}; the server checks it on upload (unknown
 * placeholders or a missing {{body}} are refused).
 */
export function TemplateManager() {
  const { token, logout } = useAuth();
  const [templates, setTemplates] = useState<DocumentTemplateInfo[]>([]);
  const [placeholders, setPlaceholders] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
      const response = await listTemplates(token);
      setTemplates(response.templates);
      setPlaceholders(response.placeholders);
    } catch (err) {
      failure(err, "Could not load templates.");
    } finally {
      setIsLoading(false);
    }
  }, [token, failure]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!token || !file) return;
    setIsUploading(true);
    setError(null);
    try {
      await uploadTemplate(name.trim() || file.name.replace(/\.docx$/i, ""), file, token);
      setName("");
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      await load();
    } catch (err) {
      failure(err, "Could not upload the template.");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleDownload(template: DocumentTemplateInfo) {
    if (!token) return;
    try {
      const url = URL.createObjectURL(await downloadTemplate(template.id, token));
      const link = document.createElement("a");
      link.href = url;
      link.download = template.original_filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      failure(err, "Could not download the template.");
    }
  }

  async function handleDelete(template: DocumentTemplateInfo) {
    if (!token || !window.confirm(`Delete the template "${template.name}"?`)) return;
    try {
      await deleteTemplate(template.id, token);
      await load();
    } catch (err) {
      failure(err, "Could not delete the template.");
    }
  }

  if (isLoading) return <LoadingSpinner label="Loading templates..." />;

  return (
    <div>
      <p style={{ fontSize: "0.85rem", color: "#555", marginTop: 0 }}>
        Upload your firm&apos;s own Word (.docx) pleading paper. Put <code>{"{{body}}"}</code> on a line of its own where
        the complaint&apos;s text goes. You can also use:{" "}
        {placeholders
          .filter((p) => p !== "body")
          .map((p) => (
            <code key={p} style={{ marginRight: "0.4rem" }}>{`{{${p}}}`}</code>
          ))}
      </p>

      <form onSubmit={handleUpload} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <input
          placeholder="Template name"
          aria-label="Template name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={isUploading}
        />
        <input
          ref={inputRef}
          type="file"
          accept=".docx"
          aria-label="Template file"
          disabled={isUploading}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" disabled={!file || isUploading}>
          {isUploading ? "Checking..." : "Upload template"}
        </button>
      </form>

      {error && <ErrorMessage message={error} />}

      {templates.length === 0 ? (
        <p style={{ color: "#777", fontSize: "0.85rem" }}>
          No templates yet - complaints use the built-in California pleading paper.
        </p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, marginTop: "0.75rem" }}>
          {templates.map((template) => (
            <li
              key={template.id}
              style={{ display: "flex", justifyContent: "space-between", padding: "0.4rem 0", borderBottom: "1px solid #eee" }}
            >
              <span style={{ fontSize: "0.85rem" }}>
                <strong>{template.name}</strong> ({template.original_filename})
                <span style={{ color: "#777", marginLeft: "0.5rem" }}>
                  uses {template.placeholders.map((p) => `{{${p}}}`).join(" ")}
                </span>
              </span>
              <span style={{ whiteSpace: "nowrap" }}>
                <button type="button" onClick={() => handleDownload(template)}>
                  Download
                </button>{" "}
                <button type="button" onClick={() => handleDelete(template)} aria-label={`Delete ${template.name}`}>
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

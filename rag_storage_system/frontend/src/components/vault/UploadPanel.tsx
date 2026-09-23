"use client";

import { useRef, useState } from "react";

import type { UploadedFileResult } from "@/lib/api/types";

interface UploadPanelProps {
  currentPath: string;
  onUpload: (files: File[]) => Promise<void>;
  isUploading: boolean;
  uploadError: string | null;
  uploadResults: UploadedFileResult[] | null;
}

const ACCEPTED_EXTENSIONS = ".pdf,.docx,.txt";

/**
 * Uploads real files to the current folder via
 * POST /categories/{category}/documents/batch. Every entry in
 * `uploadResults` after a submit is exactly what the backend reported
 * for that file (stored, or rejected with the backend's own reason) -
 * this never guesses whether a file succeeded.
 */
export function UploadPanel({ currentPath, onUpload, isUploading, uploadError, uploadResults }: UploadPanelProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  if (currentPath === "") {
    return <p style={{ color: "#777" }}>Select or create a folder above to upload documents into it.</p>;
  }

  async function handleSubmit() {
    if (selectedFiles.length === 0) return;
    await onUpload(selectedFiles);
    setSelectedFiles([]);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS}
        disabled={isUploading}
        onChange={(e) => setSelectedFiles(Array.from(e.target.files ?? []))}
      />

      <button type="button" onClick={handleSubmit} disabled={isUploading || selectedFiles.length === 0} style={{ marginLeft: "0.5rem" }}>
        {isUploading ? "Uploading..." : `Upload to ${currentPath}`}
      </button>

      {uploadError && <p style={{ color: "#c0392b", fontSize: "0.85rem" }}>{uploadError}</p>}

      {uploadResults && (
        <ul style={{ listStyle: "none", margin: "0.5rem 0 0 0", padding: 0, fontSize: "0.85rem" }}>
          {uploadResults.map((result, i) => (
            <li key={i} style={{ color: result.status === "stored" ? "#2e7d32" : "#c0392b" }}>
              {result.filename}: {result.status === "stored" ? "uploaded" : `rejected - ${result.reason}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
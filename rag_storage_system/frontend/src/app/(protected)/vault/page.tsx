"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth/useAuth";
import {
  createCategory,
  deleteDocument,
  getProcessingStatus,
  listCategories,
  listDocuments,
  startProcessing,
  uploadDocuments,
} from "@/lib/api/documents";
import type { CategoryInfo, DocumentInfo, ProcessStatusResponse, UploadedFileResult } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { FolderBrowser } from "@/components/vault/FolderBrowser";
import { DocumentList } from "@/components/vault/DocumentList";
import { UploadPanel } from "@/components/vault/UploadPanel";

const PROCESS_POLL_INTERVAL_MS = 2000;

/**
 * The real Owner Vault - categories/folders, documents, and their
 * processing status, all from the existing backend endpoints
 * (GET/POST /categories, GET /documents,
 * POST /categories/{category}/documents/batch,
 * DELETE /categories/{category}/documents/{filename}, POST /process,
 * GET /process/{job_id} - app/api/storage_api.py). No new backend
 * logic - this only calls what already exists and renders exactly
 * what it returns.
 */
export default function VaultPage() {
  const { token, logout } = useAuth();

  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [isLoadingCategories, setIsLoadingCategories] = useState(true);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);

  const [currentPath, setCurrentPath] = useState("");
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [createFolderError, setCreateFolderError] = useState<string | null>(null);

  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadResults, setUploadResults] = useState<UploadedFileResult[] | null>(null);

  const [deletingFilename, setDeletingFilename] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [isProcessing, setIsProcessing] = useState(false);
  const [processStatus, setProcessStatus] = useState<ProcessStatusResponse | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);

  const handleAuthFailure = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return true;
      }
      return false;
    },
    [logout]
  );

  const refreshCategories = useCallback(async () => {
    setIsLoadingCategories(true);
    setCategoriesError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const response = await listCategories(token);
      setCategories(response.categories);
    } catch (err) {
      if (handleAuthFailure(err)) return;
      setCategoriesError(err instanceof ApiError ? err.message : "Could not load folders.");
    } finally {
      setIsLoadingCategories(false);
    }
  }, [token, handleAuthFailure]);

  const refreshDocuments = useCallback(async () => {
    if (currentPath === "") {
      // Nothing lives directly at the root - only top-level folders do.
      setDocuments([]);
      setDocumentsError(null);
      setIsLoadingDocuments(false);
      return;
    }

    setIsLoadingDocuments(true);
    setDocumentsError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const response = await listDocuments(token, currentPath);
      // GET /documents?category=X also returns X's subfolders' files -
      // keep only the ones that live directly in this exact folder.
      setDocuments(response.documents.filter((doc) => doc.category === currentPath));
    } catch (err) {
      if (handleAuthFailure(err)) return;
      setDocumentsError(err instanceof ApiError ? err.message : "Could not load documents.");
    } finally {
      setIsLoadingDocuments(false);
    }
  }, [token, currentPath, handleAuthFailure]);

  useEffect(() => {
    // Fetching on mount is exactly what this effect is for - there's
    // no earlier synchronous point to read this from, same case the
    // set-state-in-effect rule is meant to allow.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshCategories();
  }, [refreshCategories]);

  useEffect(() => {
    // Re-fetches whenever currentPath changes (folder navigation) -
    // same legitimate case as above.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshDocuments();
  }, [refreshDocuments]);

  function handleNavigate(path: string) {
    setCurrentPath(path);
    setUploadResults(null);
    setUploadError(null);
    setDeleteError(null);
  }

  async function handleCreateFolder(name: string) {
    setIsCreatingFolder(true);
    setCreateFolderError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      await createCategory({ name, parent: currentPath || undefined }, token);
      await refreshCategories();
    } catch (err) {
      if (handleAuthFailure(err)) return;
      setCreateFolderError(err instanceof ApiError ? err.message : "Could not create folder.");
    } finally {
      setIsCreatingFolder(false);
    }
  }

  async function handleUpload(files: File[]) {
    setIsUploading(true);
    setUploadError(null);
    setUploadResults(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const response = await uploadDocuments(currentPath, files, token);
      setUploadResults(response.results);
      await Promise.all([refreshDocuments(), refreshCategories()]);
    } catch (err) {
      if (handleAuthFailure(err)) return;
      setUploadError(err instanceof ApiError ? err.message : "Upload failed. Please try again.");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleDelete(filename: string) {
    if (!window.confirm(`Delete "${filename}"? This cannot be undone.`)) return;

    setDeletingFilename(filename);
    setDeleteError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      await deleteDocument(currentPath, filename, token);
      await Promise.all([refreshDocuments(), refreshCategories()]);
    } catch (err) {
      if (handleAuthFailure(err)) return;
      setDeleteError(err instanceof ApiError ? err.message : "Could not delete this document.");
    } finally {
      setDeletingFilename(null);
    }
  }

  async function handleStartProcessing() {
    setIsProcessing(true);
    setProcessError(null);
    setProcessStatus(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }
      const queued = await startProcessing(token);
      pollProcessingStatus(queued.job_id, token);
    } catch (err) {
      setIsProcessing(false);
      if (handleAuthFailure(err)) return;
      setProcessError(err instanceof ApiError ? err.message : "Could not start processing.");
    }
  }

  function pollProcessingStatus(jobId: string, activeToken: string) {
    const poll = async () => {
      try {
        const status = await getProcessingStatus(jobId, activeToken);
        setProcessStatus(status);

        if (status.status === "finished" || status.status === "failed") {
          setIsProcessing(false);
          await Promise.all([refreshDocuments(), refreshCategories()]);
          return;
        }

        setTimeout(poll, PROCESS_POLL_INTERVAL_MS);
      } catch (err) {
        setIsProcessing(false);
        if (handleAuthFailure(err)) return;
        setProcessError(err instanceof ApiError ? err.message : "Lost track of the processing job.");
      }
    };

    poll();
  }

  return (
    <div style={{ maxWidth: 800, margin: "0 auto" }}>
      <h1>Vault</h1>
      <p style={{ color: "#666" }}>
        Manage the firm&apos;s document library: create folders, upload PDF/DOCX/TXT files, and
        track each document&apos;s real processing status.
      </p>

      <section style={{ marginTop: "1.5rem" }}>
        {isLoadingCategories ? (
          <LoadingSpinner label="Loading folders..." />
        ) : categoriesError ? (
          <ErrorMessage message={categoriesError} />
        ) : (
          <FolderBrowser
            categories={categories}
            currentPath={currentPath}
            onNavigate={handleNavigate}
            onCreateFolder={handleCreateFolder}
            isCreatingFolder={isCreatingFolder}
            createFolderError={createFolderError}
          />
        )}
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>Upload</h2>
        <UploadPanel
          currentPath={currentPath}
          onUpload={handleUpload}
          isUploading={isUploading}
          uploadError={uploadError}
          uploadResults={uploadResults}
        />
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ fontSize: "1rem", color: "#555", margin: 0 }}>Documents</h2>
          <button type="button" onClick={handleStartProcessing} disabled={isProcessing}>
            {isProcessing ? "Processing..." : "Process all documents"}
          </button>
        </div>

        {processStatus && (
          <p style={{ fontSize: "0.85rem", color: processStatus.status === "failed" ? "#c0392b" : "#666" }}>
            Job {processStatus.job_id}: {processStatus.status}
            {processStatus.result &&
              ` - ${processStatus.result.documents_extracted} extracted, ${processStatus.result.chunks_created} chunks, ${processStatus.result.embeddings_created} embeddings`}
            {processStatus.error && ` - ${processStatus.error}`}
          </p>
        )}
        {processError && <ErrorMessage message={processError} />}

        {isLoadingDocuments ? (
          <LoadingSpinner label="Loading documents..." />
        ) : documentsError ? (
          <ErrorMessage message={documentsError} />
        ) : (
          <>
            {deleteError && <ErrorMessage message={deleteError} />}
            <DocumentList documents={documents} onDelete={handleDelete} deletingFilename={deletingFilename} />
          </>
        )}
      </section>
    </div>
  );
}
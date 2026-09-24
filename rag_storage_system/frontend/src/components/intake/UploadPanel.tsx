"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { listIntakeUploads, uploadIntakeFile } from "@/lib/api/intake";
import type { ExtractedInformationInfo, UploadedInputDetailResponse } from "@/lib/api/types";
import { ErrorMessage } from "@/components/ui/ErrorMessage";

// Mirrors the backend's default INTAKE_ALLOWED_EXTENSIONS (config/settings.py).
// The backend is still the one that decides - this only filters the file picker.
const ACCEPTED_EXTENSIONS = ".png,.jpg,.jpeg,.tiff,.bmp,.mp3,.wav,.m4a,.mp4,.mov,.avi,.pdf,.docx,.txt,.zip";
const POLL_INTERVAL_MS = 3000;

type Lang = "en" | "es";

const TEXT = {
  en: {
    title: "Your files",
    help: "Add photos, audio recordings, videos, or documents that support your case. They're only shared with the firm reviewing your intake.",
    button: "Add photos, audio or video",
    uploading: "Uploading",
    empty: "No files added yet.",
    show: "Show what was found",
    hide: "Hide",
    nothingFound: "Nothing could be extracted from this file.",
    placeholder: "placeholder - automatic reading isn't set up yet, the firm will review the original file",
    status: {
      queued: "Waiting to be processed",
      processing: "Processing...",
      completed: "Done",
      partial: "Partly processed",
      failed: "Couldn't be processed",
    } as Record<string, string>,
    media: { image: "Photo", audio: "Audio", video: "Video", document: "Document", archive: "ZIP" } as Record<string, string>,
    content: {
      text: "Document text",
      ocr_text: "Text found in the image",
      caption: "Image description",
      transcript: "Transcript",
      frame_caption: "Video scene",
    } as Record<string, string>,
  },
  es: {
    title: "Sus archivos",
    help: "Agregue fotos, grabaciones de audio, videos o documentos que respalden su caso. Solo se comparten con el despacho que revisa su admision.",
    button: "Agregar fotos, audio o video",
    uploading: "Subiendo",
    empty: "Todavia no ha agregado archivos.",
    show: "Ver lo que se encontro",
    hide: "Ocultar",
    nothingFound: "No se pudo extraer nada de este archivo.",
    placeholder: "texto provisional - la lectura automatica aun no esta configurada, el despacho revisara el archivo original",
    status: {
      queued: "En espera de procesamiento",
      processing: "Procesando...",
      completed: "Listo",
      partial: "Procesado en parte",
      failed: "No se pudo procesar",
    } as Record<string, string>,
    media: { image: "Foto", audio: "Audio", video: "Video", document: "Documento", archive: "ZIP" } as Record<string, string>,
    content: {
      text: "Texto del documento",
      ocr_text: "Texto encontrado en la imagen",
      caption: "Descripcion de la imagen",
      transcript: "Transcripcion",
      frame_caption: "Escena del video",
    } as Record<string, string>,
  },
};

const STATUS_COLORS: Record<string, { background: string; color: string }> = {
  queued: { background: "#f0f0f0", color: "#555" },
  processing: { background: "#eaf1fb", color: "#1a5fb4" },
  completed: { background: "#eaf6ea", color: "#2e6b2e" },
  partial: { background: "#fff8e6", color: "#8a6116" },
  failed: { background: "#fdecea", color: "#c0392b" },
};

interface InFlightUpload {
  localId: number;
  name: string;
  percent: number;
}

function formatSize(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  if (bytes >= 1_000) return `${Math.round(bytes / 1_000)} KB`;
  return `${bytes} B`;
}

function ExtractedItem({ item, t }: { item: ExtractedInformationInfo; t: (typeof TEXT)[Lang] }) {
  return (
    <li style={{ marginBottom: "0.5rem" }}>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#555" }}>
        {t.content[item.content_type] ?? item.content_type}
        {item.archive_member_filename && ` - ${item.archive_member_filename}`}
      </div>
      {item.is_mock ? (
        <div style={{ fontSize: "0.8rem", color: "#8a6116", fontStyle: "italic" }}>({t.placeholder})</div>
      ) : (
        <div style={{ fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>{item.text}</div>
      )}
    </li>
  );
}

interface UploadPanelProps {
  sessionId: number;
  endUserToken: string;
  language: string | null;
  onUnauthorized: () => void;
}

/**
 * Lets the client attach evidence (photos, audio, video, documents, or
 * a ZIP) to their intake session. Each file is processed on the server
 * - text read from photos (OCR), a description of the image, speech
 * transcribed from audio/video, and descriptions of video scenes - and
 * the panel polls until processing finishes, then shows what was found.
 */
export function UploadPanel({ sessionId, endUserToken, language, onUnauthorized }: UploadPanelProps) {
  const t = TEXT[language === "es" ? "es" : "en"];

  const [uploads, setUploads] = useState<UploadedInputDetailResponse[]>([]);
  const [inFlight, setInFlight] = useState<InFlightUpload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const localIdCounter = useRef(0);

  const handleError = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setError(err instanceof ApiError ? err.message : fallback);
    },
    [onUnauthorized]
  );

  const loadUploads = useCallback(async () => {
    try {
      const response = await listIntakeUploads(sessionId, endUserToken);
      setUploads(response.uploads);
    } catch (err) {
      handleError(err, "Could not load your files.");
    }
  }, [sessionId, endUserToken, handleError]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUploads();
  }, [loadUploads]);

  const isStillProcessing = uploads.some((u) =>
    ["queued", "processing"].includes(u.uploaded_input.processing_status)
  );

  useEffect(() => {
    if (!isStillProcessing) return;
    const timer = setTimeout(() => {
      void loadUploads();
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [isStillProcessing, uploads, loadUploads]);

  async function handleFilesChosen(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);

    // One at a time: several large videos uploading in parallel would
    // only compete for the same connection.
    for (const file of Array.from(files)) {
      localIdCounter.current += 1;
      const localId = localIdCounter.current;
      setInFlight((prev) => [...prev, { localId, name: file.name, percent: 0 }]);

      try {
        await uploadIntakeFile(sessionId, file, endUserToken, (percent) =>
          setInFlight((prev) => prev.map((u) => (u.localId === localId ? { ...u, percent } : u)))
        );
        await loadUploads();
      } catch (err) {
        handleError(err, `Could not upload ${file.name}.`);
      } finally {
        setInFlight((prev) => prev.filter((u) => u.localId !== localId));
      }
    }

    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function toggleExpanded(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section
      style={{ marginTop: "1.25rem", border: "1px solid #e5e5e5", borderRadius: 6, padding: "0.75rem 1rem" }}
    >
      <h2 style={{ fontSize: "1rem", margin: "0 0 0.25rem 0" }}>{t.title}</h2>
      <p style={{ fontSize: "0.85rem", color: "#666", margin: "0 0 0.75rem 0" }}>{t.help}</p>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS}
        onChange={(e) => handleFilesChosen(e.target.files)}
        style={{ display: "none" }}
        aria-label={t.button}
      />
      <button type="button" onClick={() => fileInputRef.current?.click()} disabled={inFlight.length > 0}>
        {t.button}
      </button>

      {error && (
        <div style={{ marginTop: "0.75rem" }}>
          <ErrorMessage message={error} />
        </div>
      )}

      {inFlight.map((u) => (
        <div key={u.localId} style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
          {t.uploading} {u.name} - {u.percent}%
          <div style={{ height: 6, background: "#eee", borderRadius: 3, marginTop: 4 }}>
            <div style={{ width: `${u.percent}%`, height: "100%", background: "#1a5fb4", borderRadius: 3 }} />
          </div>
        </div>
      ))}

      {uploads.length === 0 && inFlight.length === 0 && (
        <p style={{ fontSize: "0.85rem", color: "#777", margin: "0.75rem 0 0 0" }}>{t.empty}</p>
      )}

      {uploads.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: "0.75rem 0 0 0", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {uploads.map(({ uploaded_input: upload, extracted_information: extracted }) => {
            const status = upload.processing_status;
            const colors = STATUS_COLORS[status] ?? STATUS_COLORS.queued;
            const isDone = status === "completed" || status === "partial";
            const isOpen = expanded.has(upload.id);

            return (
              <li key={upload.id} style={{ border: "1px solid #eee", borderRadius: 4, padding: "0.5rem 0.75rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
                  <span style={{ fontSize: "0.9rem", wordBreak: "break-all" }}>
                    <strong>{t.media[upload.media_type] ?? upload.media_type}</strong> - {upload.original_filename}{" "}
                    <span style={{ color: "#888", fontSize: "0.8rem" }}>({formatSize(upload.size)})</span>
                  </span>
                  <span
                    style={{
                      ...colors,
                      fontSize: "0.75rem",
                      borderRadius: 12,
                      padding: "0.1rem 0.5rem",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t.status[status] ?? status}
                  </span>
                </div>

                {upload.status_detail && (status === "failed" || status === "partial") && (
                  <div style={{ fontSize: "0.8rem", color: "#c0392b", marginTop: "0.25rem" }}>{upload.status_detail}</div>
                )}

                {isDone && (
                  <button
                    type="button"
                    onClick={() => toggleExpanded(upload.id)}
                    style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}
                  >
                    {isOpen ? t.hide : t.show}
                  </button>
                )}

                {isDone && isOpen && (
                  <ul style={{ listStyle: "none", padding: 0, margin: "0.5rem 0 0 0" }}>
                    {extracted.length === 0 ? (
                      <li style={{ fontSize: "0.85rem", color: "#777" }}>{t.nothingFound}</li>
                    ) : (
                      extracted.map((item) => <ExtractedItem key={item.id} item={item} t={t} />)
                    )}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

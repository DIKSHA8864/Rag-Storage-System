"use client";

import { useEffect, useRef, useState } from "react";

export type CaptureKind = "audio" | "video" | "photo";

type Lang = "en" | "es";

const MAX_RECORDING_SECONDS = 10 * 60;

const TEXT = {
  en: {
    starting: "Starting your camera / microphone...",
    recording: "Recording",
    stop: "Stop",
    takePhoto: "Take photo",
    save: "Add to my files",
    retake: "Record again",
    retakePhoto: "Take again",
    cancel: "Cancel",
    denied: "Your browser blocked the camera/microphone. Allow access in the address bar, then try again.",
    notFound: "No camera or microphone was found on this device.",
    unsupported: "This browser can't record here. Use 'Upload a file' instead.",
    failed: "Could not start recording.",
    limit: "Recording stops automatically after 10 minutes.",
  },
  es: {
    starting: "Iniciando la camara / el microfono...",
    recording: "Grabando",
    stop: "Detener",
    takePhoto: "Tomar foto",
    save: "Agregar a mis archivos",
    retake: "Grabar de nuevo",
    retakePhoto: "Tomar otra",
    cancel: "Cancelar",
    denied: "Su navegador bloqueo la camara/el microfono. Permita el acceso en la barra de direcciones e intente de nuevo.",
    notFound: "No se encontro camara ni microfono en este dispositivo.",
    unsupported: "Este navegador no puede grabar aqui. Use 'Subir un archivo'.",
    failed: "No se pudo iniciar la grabacion.",
    limit: "La grabacion se detiene automaticamente a los 10 minutos.",
  },
};

// Each browser records a different container; the backend picks audio vs
// video processing by extension (app/multimodal/models.py), so the saved
// file name must say which one it is.
const AUDIO_FORMATS = [
  { mimeType: "audio/webm;codecs=opus", extension: ".weba" },
  { mimeType: "audio/webm", extension: ".weba" },
  { mimeType: "audio/ogg;codecs=opus", extension: ".ogg" },
  { mimeType: "audio/mp4", extension: ".m4a" },
];
const VIDEO_FORMATS = [
  { mimeType: "video/webm;codecs=vp8,opus", extension: ".webm" },
  { mimeType: "video/webm", extension: ".webm" },
  { mimeType: "video/mp4", extension: ".mp4" },
];

function pickFormat(kind: "audio" | "video") {
  const formats = kind === "audio" ? AUDIO_FORMATS : VIDEO_FORMATS;
  return formats.find((f) => MediaRecorder.isTypeSupported(f.mimeType)) ?? null;
}

function timestampName(prefix: string, extension: string): string {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return `${prefix}-${stamp}${extension}`;
}

function formatSeconds(total: number): string {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

interface MediaCaptureProps {
  kind: CaptureKind;
  language: string | null;
  onCaptured: (file: File) => void;
  onClose: () => void;
}

/**
 * Records audio or video, or takes a photo, with the device's own
 * microphone/camera - so a client can capture evidence right on the
 * intake page instead of finding a file. The result is previewed first;
 * only "Add to my files" hands it to the normal upload (the same
 * endpoint and processing as an uploaded file).
 */
export function MediaCapture({ kind, language, onCaptured, onClose }: MediaCaptureProps) {
  const t = TEXT[language === "es" ? "es" : "en"] as (typeof TEXT)[Lang];

  const [phase, setPhase] = useState<"starting" | "live" | "review">("starting");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [captured, setCaptured] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const liveVideoRef = useRef<HTMLVideoElement>(null);

  // Open the camera/microphone (again, after "record again").
  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia || (kind !== "photo" && typeof MediaRecorder === "undefined")) {
        setError(t.unsupported);
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia(
          kind === "audio" ? { audio: true } : kind === "video" ? { audio: true, video: true } : { video: true }
        );
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (liveVideoRef.current) liveVideoRef.current.srcObject = stream;

        if (kind !== "photo") {
          const format = pickFormat(kind);
          if (!format) {
            setError(t.unsupported);
            return;
          }
          const chunks: Blob[] = [];
          const recorder = new MediaRecorder(stream, { mimeType: format.mimeType });
          recorder.ondataavailable = (event) => {
            if (event.data.size > 0) chunks.push(event.data);
          };
          recorder.onstop = () => {
            stream.getTracks().forEach((track) => track.stop());
            const blob = new Blob(chunks, { type: format.mimeType.split(";")[0] });
            const file = new File([blob], timestampName(kind === "audio" ? "recording" : "video", format.extension), {
              type: blob.type,
            });
            setCaptured(file);
            setPreviewUrl(URL.createObjectURL(blob));
            setPhase("review");
          };
          recorderRef.current = recorder;
          recorder.start(1000);
        }
        setPhase("live");
      } catch (err) {
        const name = err instanceof DOMException ? err.name : "";
        setError(name === "NotAllowedError" ? t.denied : name === "NotFoundError" ? t.notFound : t.failed);
      }
    }

    void start();

    return () => {
      cancelled = true;
      if (recorderRef.current?.state === "recording") {
        recorderRef.current.onstop = null;
        recorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
    // `t` only changes with language; restarting the camera for that isn't wanted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, attempt]);

  // Recording timer, with an automatic stop at the limit.
  useEffect(() => {
    if (phase !== "live" || kind === "photo") return;
    const timer = setInterval(() => {
      setElapsed((seconds) => {
        if (seconds + 1 >= MAX_RECORDING_SECONDS && recorderRef.current?.state === "recording") {
          recorderRef.current.stop();
        }
        return seconds + 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [phase, kind]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  function takePhoto() {
    const video = liveVideoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        streamRef.current?.getTracks().forEach((track) => track.stop());
        setCaptured(new File([blob], timestampName("photo", ".jpg"), { type: "image/jpeg" }));
        setPreviewUrl(URL.createObjectURL(blob));
        setPhase("review");
      },
      "image/jpeg",
      0.92
    );
  }

  function again() {
    setCaptured(null);
    setPreviewUrl(null);
    setElapsed(0);
    setError(null);
    setPhase("starting");
    setAttempt((n) => n + 1);
  }

  return (
    <div style={{ border: "1px solid #d6e4f5", background: "#f7faff", borderRadius: 6, padding: "0.75rem", marginTop: "0.75rem" }}>
      {error ? (
        <>
          <p style={{ color: "#c0392b", fontSize: "0.85rem", margin: "0 0 0.5rem 0" }}>{error}</p>
          <button type="button" onClick={onClose}>
            {t.cancel}
          </button>
        </>
      ) : (
        <>
          {phase === "starting" && <p style={{ fontSize: "0.85rem", color: "#555", margin: 0 }}>{t.starting}</p>}

          {kind !== "audio" && phase !== "review" && (
            <video
              ref={liveVideoRef}
              autoPlay
              muted
              playsInline
              style={{ width: "100%", maxHeight: 280, background: "#000", borderRadius: 4, display: phase === "live" ? "block" : "none" }}
            />
          )}

          {phase === "live" && (
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.5rem", flexWrap: "wrap" }}>
              {kind === "photo" ? (
                <button type="button" onClick={takePhoto}>
                  {t.takePhoto}
                </button>
              ) : (
                <>
                  <span style={{ color: "#c0392b", fontSize: "0.85rem", fontWeight: 600 }} aria-live="polite">
                    ● {t.recording} {formatSeconds(elapsed)}
                  </span>
                  <button type="button" onClick={stopRecording}>
                    {t.stop}
                  </button>
                </>
              )}
              <button type="button" onClick={onClose}>
                {t.cancel}
              </button>
              {kind !== "photo" && <span style={{ fontSize: "0.75rem", color: "#888" }}>{t.limit}</span>}
            </div>
          )}

          {phase === "review" && captured && previewUrl && (
            <div>
              {kind === "audio" && <audio controls src={previewUrl} style={{ width: "100%" }} />}
              {kind === "video" && <video controls playsInline src={previewUrl} style={{ width: "100%", maxHeight: 280, borderRadius: 4 }} />}
              {/* A blob: preview of the photo just taken - next/image adds nothing for a local object URL. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {kind === "photo" && <img src={previewUrl} alt="" style={{ width: "100%", maxHeight: 280, objectFit: "contain", borderRadius: 4 }} />}
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
                <button type="button" onClick={() => onCaptured(captured)}>
                  {t.save}
                </button>
                <button type="button" onClick={again}>
                  {kind === "photo" ? t.retakePhoto : t.retake}
                </button>
                <button type="button" onClick={onClose}>
                  {t.cancel}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

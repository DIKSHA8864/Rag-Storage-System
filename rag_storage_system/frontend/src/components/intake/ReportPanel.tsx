"use client";

import { useEffect, useState } from "react";

import { downloadIntakeReport, generateIntakeReport } from "@/lib/api/intake";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { loadIntakeReportId, saveIntakeReportId } from "@/lib/clientAuth/intakeReportStorage";

interface ReportPanelProps {
  sessionId: number;
  endUserKey: string;
  language: string | null;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Generates and downloads the real intake report (POST/GET
 * .../report, app/api/intake_api.py) - built entirely from this
 * session's actual facts, timeline, and uploads
 * (app/report/builder.py), separating client-reported facts from any
 * knowledge-base-grounded legal research (app/report/rag_analysis.py,
 * always citation-backed, never an invented conclusion). Every
 * generated report requires Owner/attorney approval
 * (POST /admin/reports/{id}/approve) before this component can
 * download it - that gate is enforced server-side, not skipped here.
 */
export function ReportPanel({ sessionId, endUserKey, language }: ReportPanelProps) {
  const [reportId, setReportId] = useState<number | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState<string | null>(null);

  useEffect(() => {
    // localStorage doesn't exist during SSR, so the saved report id
    // can only be read after mount - same legitimate case as
    // AuthContext.tsx's own session-hydration effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReportId(loadIntakeReportId());
  }, []);

  const isEs = language === "es";

  async function handleGenerate() {
    setGenerateError(null);
    setIsGenerating(true);

    try {
      const report = await generateIntakeReport(sessionId, { format: "pdf" }, endUserKey);
      saveIntakeReportId(report.id);
      setReportId(report.id);
    } catch (err) {
      setGenerateError(
        err instanceof ApiError ? err.message : isEs ? "No se pudo generar el informe." : "Could not generate the report."
      );
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDownload() {
    if (!reportId) return;

    setDownloadNotice(null);
    setIsDownloading(true);

    try {
      const blob = await downloadIntakeReport(reportId, endUserKey);
      downloadBlob(blob, `intake-report-${reportId}.pdf`);
    } catch (err) {
      setDownloadNotice(
        err instanceof ApiError ? err.message : isEs ? "No se pudo descargar el informe." : "Could not download the report."
      );
    } finally {
      setIsDownloading(false);
    }
  }

  return (
    <div style={{ marginTop: "1.5rem", borderTop: "1px solid #e5e5e5", paddingTop: "1rem" }}>
      <h2 style={{ fontSize: "1rem" }}>{isEs ? "Su informe" : "Your report"}</h2>

      {!reportId ? (
        <>
          <p style={{ fontSize: "0.85rem", color: "#666" }}>
            {isEs
              ? "Puede generar un informe con la informacion que compartio. Un abogado debe aprobarlo antes de que pueda descargarlo."
              : "You can generate a report from the information you shared. An attorney must approve it before you can download it."}
          </p>
          <button type="button" onClick={handleGenerate} disabled={isGenerating}>
            {isGenerating ? (isEs ? "Generando..." : "Generating...") : isEs ? "Generar informe (PDF)" : "Generate report (PDF)"}
          </button>
          {generateError && <ErrorMessage message={generateError} />}
        </>
      ) : (
        <>
          <p style={{ fontSize: "0.85rem", color: "#666" }}>
            {isEs
              ? "Su informe fue generado y esta pendiente de revision por un abogado."
              : "Your report has been generated and is pending attorney review."}
          </p>
          <button type="button" onClick={handleDownload} disabled={isDownloading}>
            {isDownloading ? (isEs ? "Comprobando..." : "Checking...") : isEs ? "Descargar informe" : "Download report"}
          </button>
          {downloadNotice && <p style={{ fontSize: "0.85rem", color: "#8a6116", marginTop: "0.5rem" }}>{downloadNotice}</p>}
        </>
      )}
    </div>
  );
}
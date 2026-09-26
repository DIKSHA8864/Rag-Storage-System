"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { useAuth } from "@/lib/auth/useAuth";
import { getAdminStats, listAllDocuments, listCategories } from "@/lib/api/documents";
import { approveReport, listPendingReports, rejectReport } from "@/lib/api/reports";
import type { AdminStats, CategoryInfo, DocumentInfo, PendingReportInfo } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { TodayPanel } from "@/components/dashboard/TodayPanel";

const RECENT_UPLOADS_LIMIT = 5;

const STATUS_COLORS: Record<string, { background: string; color: string }> = {
  Uploaded: { background: "#eaf1fb", color: "#1a5fb4" },
  Processing: { background: "#fff8e6", color: "#8a6116" },
  Embedding: { background: "#fff8e6", color: "#8a6116" },
  Indexed: { background: "#e8f5e9", color: "#2e7d32" },
  Failed: { background: "#fdecea", color: "#c0392b" },
};

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * The real Owner Dashboard - every number here comes from the
 * existing GET /admin/stats, GET /categories, GET /documents, and
 * GET /admin/reports/pending (app/api/storage_api.py). No separate
 * stats system: this reads exactly what those endpoints return and
 * never estimates or invents a number they don't provide.
 */
export default function DashboardPage() {
  const { token, logout } = useAuth();

  const [stats, setStats] = useState<AdminStats | null>(null);
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [pendingReports, setPendingReports] = useState<PendingReportInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reviewingReportId, setReviewingReportId] = useState<number | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (!token) {
        throw new ApiError(401, "Session expired. Please log in again.");
      }

      const [statsResponse, categoriesResponse, documentsResponse, pendingReportsResponse] = await Promise.all([
        getAdminStats(token),
        listCategories(token),
        listAllDocuments(token),
        listPendingReports(token),
      ]);

      setStats(statsResponse);
      setCategories(categoriesResponse.categories);
      setDocuments(documentsResponse.documents);
      setPendingReports(pendingReportsResponse.reports);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load the dashboard.");
    } finally {
      setIsLoading(false);
    }
  }, [token, logout]);

  const refreshPendingReports = useCallback(async () => {
    if (!token) return;
    try {
      const response = await listPendingReports(token);
      setPendingReports(response.reports);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
      }
    }
  }, [token, logout]);

  useEffect(() => {
    // Fetching on mount is exactly what this effect is for - same
    // legitimate case as the Vault page's own data-loading effects.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadDashboard();
  }, [loadDashboard]);

  async function handleApprove(reportId: number) {
    if (!token) return;
    setReviewError(null);
    setReviewingReportId(reportId);

    try {
      await approveReport(reportId, token);
      await refreshPendingReports();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setReviewError(err instanceof ApiError ? err.message : "Could not approve this report.");
    } finally {
      setReviewingReportId(null);
    }
  }

  async function handleReject(reportId: number) {
    if (!token) return;
    const reason = window.prompt("Reason for rejecting this report:");
    if (!reason || !reason.trim()) return;

    setReviewError(null);
    setReviewingReportId(reportId);

    try {
      await rejectReport(reportId, reason.trim(), token);
      await refreshPendingReports();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setReviewError(err instanceof ApiError ? err.message : "Could not reject this report.");
    } finally {
      setReviewingReportId(null);
    }
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading dashboard..." />;
  }

  if (error) {
    return (
      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        <ErrorMessage message={error} />
        <button type="button" onClick={loadDashboard} style={{ marginTop: "1rem" }}>
          Retry
        </button>
      </div>
    );
  }

  const recentUploads = [...documents]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, RECENT_UPLOADS_LIMIT);

  const failedDocuments = documents.filter((doc) => doc.status === "Failed");

  return (
    <div style={{ maxWidth: 800, margin: "0 auto" }}>
      <h1>Dashboard</h1>
      <p style={{ color: "#666" }}>What needs attention today, and a real-time view of the firm&apos;s document library.</p>

      {token && <TodayPanel token={token} onUnauthorized={logout} />}

      <h2 style={{ fontSize: "1.2rem", margin: "2rem 0 0" }}>Library</h2>

      {stats && (
        <section
          style={{
            marginTop: "1.5rem",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: "0.75rem",
          }}
        >
          <StatTile label="Documents" value={stats.total_documents} />
          <StatTile label="Categories" value={stats.total_categories} />
          <StatTile label="Storage" value={`${stats.storage_mb} MB`} />
          <StatTile label="Failed" value={stats.status_counts.Failed} emphasize={stats.status_counts.Failed > 0} />
        </section>
      )}

      {stats && (
        <section style={{ marginTop: "1.5rem" }}>
          <h2 style={{ fontSize: "1rem", color: "#555" }}>Processing status</h2>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            {Object.entries(stats.status_counts).map(([status, count]) => {
              const style = STATUS_COLORS[status] ?? { background: "#f0f0f0", color: "#555" };
              return (
                <span
                  key={status}
                  style={{ fontSize: "0.85rem", fontWeight: 600, padding: "0.25rem 0.6rem", borderRadius: 4, ...style }}
                >
                  {status}: {count}
                </span>
              );
            })}
          </div>
        </section>
      )}

      <section style={{ marginTop: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ fontSize: "1rem", color: "#555", margin: 0 }}>Categories</h2>
          <Link href="/vault">Open Vault</Link>
        </div>
        {categories.length === 0 ? (
          <p style={{ color: "#777" }}>No folders created yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: "0.5rem 0 0 0", padding: 0, display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            {categories.map((category) => (
              <li key={category.name} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem" }}>
                <span>📁 {category.name}</span>
                <span style={{ color: "#777" }}>
                  {category.document_count} document{category.document_count === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>Recent uploads</h2>
        {recentUploads.length === 0 ? (
          <p style={{ color: "#777" }}>No documents uploaded yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            {recentUploads.map((doc) => (
              <li key={doc.relative_path} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem" }}>
                <span>
                  📄 {doc.filename} <span style={{ color: "#999" }}>({doc.category})</span>
                </span>
                <span style={{ color: "#777" }}>{formatDate(doc.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", color: "#555" }}>Failed processing</h2>
        {failedDocuments.length === 0 ? (
          <p style={{ color: "#777" }}>No failed documents.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {failedDocuments.map((doc) => (
              <li
                key={doc.relative_path}
                style={{ border: "1px solid #f5c6cb", borderRadius: 4, padding: "0.5rem 0.75rem", background: "#fdecea" }}
              >
                <div style={{ fontWeight: 600, color: "#c0392b" }}>
                  📄 {doc.filename} <span style={{ fontWeight: 400 }}>({doc.category})</span>
                </div>
                {doc.status_detail && (
                  <div style={{ fontSize: "0.85rem", color: "#8a2f24", marginTop: "0.25rem" }}>{doc.status_detail}</div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 id="pending-reports" style={{ fontSize: "1rem", color: "#555", scrollMarginTop: "1rem" }}>Pending client reports</h2>
        <p style={{ fontSize: "0.8rem", color: "#999" }}>
          Generated from a Client&apos;s completed intake interview - review and approve before the Client can
          download it.
        </p>
        {reviewError && <ErrorMessage message={reviewError} />}
        {pendingReports.length === 0 ? (
          <p style={{ color: "#777" }}>No reports awaiting review.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {pendingReports.map((report) => (
              <li
                key={report.report_id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  border: "1px solid #e5e5e5",
                  borderRadius: 4,
                  padding: "0.5rem 0.75rem",
                }}
              >
                <span>
                  Report #{report.report_id} ({report.format.toUpperCase()}) - intake session #{report.intake_session_id}
                  <br />
                  <span style={{ fontSize: "0.8rem", color: "#777" }}>{formatDate(report.created_at)}</span>
                </span>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    type="button"
                    onClick={() => handleApprove(report.report_id)}
                    disabled={reviewingReportId === report.report_id}
                  >
                    {reviewingReportId === report.report_id ? "..." : "Approve"}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleReject(report.report_id)}
                    disabled={reviewingReportId === report.report_id}
                  >
                    {reviewingReportId === report.report_id ? "..." : "Reject"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function StatTile({ label, value, emphasize = false }: { label: string; value: string | number; emphasize?: boolean }) {
  return (
    <div style={{ border: "1px solid #e5e5e5", borderRadius: 6, padding: "0.75rem 1rem", background: emphasize ? "#fdecea" : "#fff" }}>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color: emphasize ? "#c0392b" : "#1a1a1a" }}>{value}</div>
      <div style={{ fontSize: "0.8rem", color: "#777" }}>{label}</div>
    </div>
  );
}
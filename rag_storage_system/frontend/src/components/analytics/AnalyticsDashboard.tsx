"use client";

import { useCallback, useEffect, useState } from "react";

import { getAnalytics } from "@/lib/api/analytics";
import { ApiError } from "@/lib/api/client";
import type { AnalyticsResponse } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";

const RANGES = [7, 30, 90];

// What each recorded answer outcome means (app/analysis/answer_generation.py).
const OUTCOMES: Record<string, { label: string; color: string }> = {
  grounded: { label: "Answered with citations", color: "#2e7d32" },
  insufficient_evidence: { label: "Honest gap (no authority in library)", color: "#1a5fb4" },
  relevance_check_unavailable: { label: "Check unavailable", color: "#b26a00" },
  fabricated_discarded: { label: "Uncited answer withheld", color: "#8e24aa" },
  claude_error_fallback: { label: "Model error - excerpts shown", color: "#c62828" },
  template_only: { label: "Excerpts only (no model key)", color: "#757575" },
  generation_error: { label: "Generation error", color: "#c62828" },
  unknown: { label: "Unknown", color: "#9e9e9e" },
};

const PURPOSES: Record<string, string> = {
  owner_research: "Owner research",
  matter_research: "Matter research",
  end_user_query: "Client Ask",
};

const card = { border: "1px solid #e5e5e5", borderRadius: 6, padding: "1rem" };
const h2 = { fontSize: "1rem", margin: "0 0 0.75rem 0" };

function formatNumber(value: number): string {
  return value.toLocaleString();
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div style={{ ...card, flex: "1 1 160px" }}>
      <div style={{ fontSize: "0.8rem", color: "#666" }}>{label}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 600, marginTop: "0.2rem" }}>{value}</div>
      {note && <div style={{ fontSize: "0.75rem", color: "#888", marginTop: "0.2rem" }}>{note}</div>}
    </div>
  );
}

function DailyChart({ perDay }: { perDay: AnalyticsResponse["questions"]["per_day"] }) {
  const width = 720;
  const height = 180;
  const pad = { left: 32, right: 8, top: 10, bottom: 24 };
  const max = Math.max(1, ...perDay.map((d) => d.count));
  const slot = (width - pad.left - pad.right) / perDay.length;
  const barWidth = Math.max(2, slot * 0.7);
  const y = (value: number) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
  const labelEvery = Math.ceil(perDay.length / 8);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Questions per day" style={{ width: "100%", height: "auto" }}>
      {[0, max].map((tick) => (
        <g key={tick}>
          <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke="#eee" />
          <text x={pad.left - 6} y={y(tick) + 4} fontSize="10" textAnchor="end" fill="#777">
            {tick}
          </text>
        </g>
      ))}
      {perDay.map((day, index) => {
        const x = pad.left + index * slot + (slot - barWidth) / 2;
        return (
          <g key={day.date}>
            <rect x={x} y={y(day.count)} width={barWidth} height={y(0) - y(day.count)} fill="#1a5fb4">
              <title>{`${day.date}: ${day.count} question${day.count === 1 ? "" : "s"}`}</title>
            </rect>
            {index % labelEvery === 0 && (
              <text x={x + barWidth / 2} y={height - 8} fontSize="10" textAnchor="middle" fill="#777">
                {day.date.slice(5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function HorizontalBars({ rows }: { rows: { label: string; value: number; color?: string; note?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      {rows.map((row) => (
        <div key={row.label} style={{ display: "grid", gridTemplateColumns: "210px 1fr 60px", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ fontSize: "0.8rem" }}>{row.label}</span>
          <div style={{ background: "#f3f3f3", borderRadius: 3, height: 14 }}>
            <div
              style={{
                width: `${(row.value / max) * 100}%`,
                minWidth: row.value ? 2 : 0,
                height: "100%",
                background: row.color ?? "#1a5fb4",
                borderRadius: 3,
              }}
            />
          </div>
          <span style={{ fontSize: "0.8rem", textAlign: "right" }}>
            {formatNumber(row.value)}
            {row.note && <span style={{ color: "#888" }}> {row.note}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Owner analytics - every number is counted from records the system already keeps. */
export function AnalyticsDashboard() {
  const { token, logout } = useAuth();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (!token) throw new ApiError(401, "Session expired. Please log in again.");
      setData(await getAnalytics(days, token));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not load analytics.");
    } finally {
      setIsLoading(false);
    }
  }, [days, token, logout]);

  useEffect(() => {
    // Page-load fetch, same pattern as every other one in this app.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const rangePicker = (
    <div role="group" aria-label="Time range" style={{ display: "flex", gap: "0.35rem" }}>
      {RANGES.map((range) => (
        <button
          key={range}
          type="button"
          onClick={() => setDays(range)}
          aria-pressed={days === range}
          style={{ fontWeight: days === range ? 700 : 400 }}
        >
          {range} days
        </button>
      ))}
    </div>
  );

  if (isLoading && !data) return <LoadingSpinner label="Loading analytics..." />;
  if (error) return <ErrorMessage message={error} />;
  if (!data) return null;

  const { questions, usage, intake } = data;
  const funnel = [
    { label: "Intakes started", value: intake.sessions },
    { label: "Interview begun", value: intake.interviews_started },
    { label: "Terms accepted", value: intake.terms_accepted },
    { label: "Interview completed", value: intake.interviews_completed },
    { label: "Report generated", value: intake.reports_generated },
    { label: "Report approved", value: intake.reports_approved },
  ].map((step) => ({
    ...step,
    note: intake.sessions && step.label !== "Intakes started" ? `(${Math.round((step.value / intake.sessions) * 100)}%)` : undefined,
  }));
  const outcomeRows = Object.entries(questions.outcomes)
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => ({ label: OUTCOMES[key]?.label ?? key, value, color: OUTCOMES[key]?.color }));
  const libraryTotal = Object.values(data.library_by_status).reduce((a, b) => a + b, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem", opacity: isLoading ? 0.6 : 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.85rem", color: "#666" }}>Since {data.since} (UTC)</span>
        {rangePicker}
      </div>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <Tile label="Questions answered" value={formatNumber(questions.total)} />
        <Tile
          label="Honest-gap rate"
          value={questions.honest_gap_rate === null ? "-" : `${Math.round(questions.honest_gap_rate * 100)}%`}
          note="of questions had no authority in the library"
        />
        <Tile
          label="Median answer time"
          value={questions.median_latency_ms === null ? "-" : `${(questions.median_latency_ms / 1000).toFixed(1)} s`}
          note={questions.p95_latency_ms === null ? undefined : `95% within ${(questions.p95_latency_ms / 1000).toFixed(1)} s`}
        />
        <Tile
          label="Model cost"
          value={usage.estimated_cost_usd === null ? "-" : `$${usage.estimated_cost_usd.toFixed(2)}`}
          note={usage.estimated_cost_usd === null ? "Set LLM_PRICES to estimate" : "estimated from token counts"}
        />
      </div>

      <section style={card}>
        <h2 style={h2}>Questions per day</h2>
        <DailyChart perDay={questions.per_day} />
        <p style={{ fontSize: "0.8rem", color: "#666", margin: "0.5rem 0 0 0" }}>
          {Object.entries(questions.by_purpose)
            .map(([purpose, count]) => `${PURPOSES[purpose] ?? purpose}: ${count}`)
            .join(" - ") || "No questions in this period."}
        </p>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: "1rem" }}>
        <section style={card}>
          <h2 style={h2}>How questions were answered</h2>
          {outcomeRows.length ? <HorizontalBars rows={outcomeRows} /> : <p style={{ color: "#777" }}>No questions yet.</p>}
        </section>
        <section style={card}>
          <h2 style={h2}>Client intake funnel</h2>
          <HorizontalBars rows={funnel} />
          <p style={{ fontSize: "0.8rem", color: "#666", margin: "0.5rem 0 0 0" }}>
            Client uploads: {intake.intake_uploads} - attorney case documents: {intake.case_documents}
          </p>
        </section>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: "1rem" }}>
        <section style={card}>
          <h2 style={h2}>Most-cited library sources</h2>
          {data.top_sources.length ? (
            <HorizontalBars rows={data.top_sources.map((s) => ({ label: `${s.filename} (${s.category})`, value: s.count }))} />
          ) : (
            <p style={{ color: "#777", fontSize: "0.85rem" }}>No cited answers in this period.</p>
          )}
        </section>
        <section style={card}>
          <h2 style={h2}>Library</h2>
          <p style={{ fontSize: "0.85rem", margin: "0 0 0.5rem 0" }}>{formatNumber(libraryTotal)} documents</p>
          <HorizontalBars
            rows={Object.entries(data.library_by_status).map(([status, count]) => ({
              label: status,
              value: count,
              color: status === "Failed" ? "#c62828" : status === "Indexed" ? "#2e7d32" : "#1a5fb4",
            }))}
          />
        </section>
      </div>

      <section style={card}>
        <h2 style={h2}>Model usage</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #e0e0e0" }}>
              <th style={{ padding: "0.3rem" }}>Model</th>
              <th style={{ padding: "0.3rem", textAlign: "right" }}>Calls</th>
              <th style={{ padding: "0.3rem", textAlign: "right" }}>Input tokens</th>
              <th style={{ padding: "0.3rem", textAlign: "right" }}>Output tokens</th>
              <th style={{ padding: "0.3rem", textAlign: "right" }}>Est. cost</th>
            </tr>
          </thead>
          <tbody>
            {usage.by_model.map((row) => (
              <tr key={row.model} style={{ borderBottom: "1px solid #f3f3f3" }}>
                <td style={{ padding: "0.3rem" }}>{row.model === "n/a" ? "No model call" : row.model === "template" ? "No model (excerpts only)" : row.model}</td>
                <td style={{ padding: "0.3rem", textAlign: "right" }}>{formatNumber(row.calls)}</td>
                <td style={{ padding: "0.3rem", textAlign: "right" }}>{formatNumber(row.input_tokens)}</td>
                <td style={{ padding: "0.3rem", textAlign: "right" }}>{formatNumber(row.output_tokens)}</td>
                <td style={{ padding: "0.3rem", textAlign: "right" }}>
                  {row.estimated_cost_usd === null ? "-" : `$${row.estimated_cost_usd.toFixed(2)}`}
                </td>
              </tr>
            ))}
            {usage.by_model.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: "0.3rem", color: "#777" }}>
                  No model calls in this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

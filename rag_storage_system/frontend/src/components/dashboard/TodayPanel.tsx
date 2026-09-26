"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api/client";
import { getToday, type TodayResponse } from "@/lib/api/today";

const STAGE_LABELS: Record<string, string> = { complete: "Complete", not_started: "Not started" };

/**
 * "Today" on the dashboard: what needs the firm's attention since the
 * start of the viewer's day. Loads on its own, so the rest of the
 * dashboard still shows if this can't.
 */
export function TodayPanel({ token, onUnauthorized }: { token: string; onUnauthorized: () => void }) {
  const [today, setToday] = useState<TodayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setToday(await getToday(token));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onUnauthorized();
        return;
      }
      setError("Today's summary couldn't be loaded.");
    }
  }, [token, onUnauthorized]);

  useEffect(() => {
    // Page-load fetch, same legitimate case as the dashboard's own.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const dateLabel = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

  return (
    <section aria-labelledby="today-heading" style={{ marginTop: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
        <h2 id="today-heading" style={{ fontSize: "1.2rem", margin: 0 }}>
          Today
        </h2>
        <span style={{ color: "#5a6573", fontSize: "0.9rem" }}>
          {dateLabel}
          {today && (
            <button type="button" onClick={load} style={{ marginLeft: "0.75rem", fontSize: "0.8rem", padding: "0.2rem 0.6rem" }}>
              Refresh
            </button>
          )}
        </span>
      </div>

      {error && <p style={{ color: "#b3261e", fontSize: "0.9rem" }}>{error}</p>}
      {!today && !error && <p style={{ color: "#5a6573" }}>Loading today&apos;s summary...</p>}

      {today && (
        <>
          <div
            style={{
              marginTop: "0.75rem",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: "0.75rem",
            }}
          >
            <TodayTile
              label="Reports to review"
              value={today.reports_pending}
              urgent={today.reports_pending > 0}
              detail={today.reports_pending > 0 ? <a href="#pending-reports">Review below</a> : "None waiting"}
            />
            <TodayTile
              label="Talk-to-a-person"
              value={today.requests_open}
              urgent={today.requests_open > 0}
              detail={
                <Link href="/requests">
                  {today.requests_open > 0 ? "Open requests" : "None open"}
                  {today.requests_claimed > 0 ? ` · ${today.requests_claimed} in progress` : ""}
                </Link>
              }
            />
            <TodayTile label="New intakes" value={today.intakes_started} detail={`${today.intakes_completed} completed`} />
            <TodayTile
              label="Questions asked"
              value={today.questions_asked}
              urgent={today.no_authority > 0}
              detail={
                today.no_authority > 0 ? (
                  <Link href="/activity">{today.no_authority} not in the library</Link>
                ) : (
                  "None missing from the library"
                )
              }
            />
            <TodayTile
              label="Uploads"
              value={today.library_uploads + today.case_documents + today.client_uploads}
              detail={`Library ${today.library_uploads} · Cases ${today.case_documents} · Clients ${today.client_uploads}`}
            />
          </div>

          <h3 style={{ fontSize: "1rem", margin: "1.25rem 0 0.5rem" }}>New client intakes today</h3>
          {today.new_intakes.length === 0 ? (
            <p style={{ color: "#5a6573", margin: 0 }}>No new intakes yet today.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {today.new_intakes.map((intake) => {
                const stage = STAGE_LABELS[intake.stage] ?? "In progress";
                const done = stage === "Complete";
                return (
                  <li
                    key={intake.intake_session_id}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "0.75rem",
                      flexWrap: "wrap",
                      padding: "0.6rem 0.85rem",
                      border: "1px solid #dde2e7",
                    }}
                  >
                    <span>
                      <Link href={`/matters/${intake.matter_id}`} style={{ fontWeight: 600 }}>
                        {intake.title}
                      </Link>
                      <span style={{ color: "#5a6573", fontSize: "0.85rem" }}>
                        {intake.client_email ? ` · ${intake.client_email}` : ""}
                        {` · ${new Date(intake.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`}
                      </span>
                    </span>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        padding: "0.15rem 0.6rem",
                        borderRadius: 999,
                        background: done ? "#e6f2e7" : "#e7eef6",
                        color: done ? "#2e7d32" : "#1f4e79",
                      }}
                    >
                      {stage}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function TodayTile({ label, value, detail, urgent = false }: { label: string; value: number; detail: ReactNode; urgent?: boolean }) {
  return (
    <div
      style={{
        padding: "0.85rem 1rem",
        border: "1px solid #dde2e7",
        boxShadow: urgent ? "inset 4px 0 0 #b8860b" : undefined,
      }}
    >
      <div style={{ fontSize: "0.72rem", letterSpacing: "0.05em", textTransform: "uppercase", color: "#5a6573", fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ fontSize: "1.8rem", fontWeight: 700, lineHeight: 1.2, margin: "0.2rem 0", fontVariantNumeric: "tabular-nums" }}>
        {value}
      </div>
      <div style={{ fontSize: "0.82rem", color: "#5a6573" }}>{detail}</div>
    </div>
  );
}

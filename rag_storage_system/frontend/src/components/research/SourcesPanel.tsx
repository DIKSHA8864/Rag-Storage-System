"use client";

import { useEffect, useState } from "react";

import type { OwnerResearchSource } from "@/lib/api/types";

const OPEN_SOURCE_EVENT = "ashilegal:open-source";

/** Called by AnswerPanel's inline citations: jump to that source AND show its passage. */
export function openSourcePassage(index: number, scope?: string) {
  window.dispatchEvent(new CustomEvent<{ index: number; scope?: string }>(OPEN_SOURCE_EVENT, { detail: { index, scope } }));
}

/** The DOM id of source card `index` - scoped when several answers share one page (a research thread). */
export function sourceElementId(index: number, scope?: string): string {
  return scope ? `${scope}-source-${index}` : `source-${index}`;
}

interface SourcesPanelProps {
  sources: OwnerResearchSource[];
  /** Set when several answers are on one page, so citations open only their own answer's sources. */
  scope?: string;
}

// Matter-scoped research (POST /admin/matters/{id}/research) mixes
// two kinds of source in the same list: the firm's shared legal
// library, and this Matter's own private documents (retrieved via
// app/matter_rag/'s "matter-{id}" category namespace - see
// app/retrieval/retriever.py's retrieve_for_matter()). Relabeling
// that raw category string here - never inventing a new field - keeps
// client-reported material visibly separate from legal authority.
function formatCategory(category: string): string {
  return category.startsWith("matter-") ? "This Matter's Documents" : category;
}

/**
 * Renders exactly the `sources` array POST /research/ask returned -
 * every entry here traces to a chunk the backend's retrieval actually
 * found (citation lock is enforced server-side; this component only
 * displays what it's given, never invents or reorders around it).
 *
 * Each card's id (source-{index}) is what AnswerPanel's inline
 * citation links jump to, and its numbered badge matches the number
 * shown in that inline citation, so it's clear which source backs
 * which part of the answer.
 *
 * Each card can show the retrieved passage itself (`excerpt`, verbatim
 * from the backend), so the reader can check the answer against the
 * library text in seconds; a citation click in AnswerPanel opens it.
 */
export function SourcesPanel({ sources, scope }: SourcesPanelProps) {
  const [openIndexes, setOpenIndexes] = useState<Set<number>>(new Set());

  useEffect(() => {
    function handleOpen(event: Event) {
      const detail = (event as CustomEvent<{ index: number; scope?: string }>).detail;
      if (detail.scope !== scope) return;
      setOpenIndexes((prev) => new Set(prev).add(detail.index));
    }
    window.addEventListener(OPEN_SOURCE_EVENT, handleOpen);
    return () => window.removeEventListener(OPEN_SOURCE_EVENT, handleOpen);
  }, [scope]);

  function toggle(index: number) {
    setOpenIndexes((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  return (
    <section
      style={{
        marginTop: "1rem",
        border: "1px solid #d0d0d0",
        borderRadius: 6,
        padding: "1rem 1.25rem",
      }}
    >
      <h2 style={{ marginTop: 0, fontSize: "1rem", color: "#555" }}>Sources</h2>

      {sources.length === 0 ? (
        <p style={{ margin: 0, color: "#777" }}>
          No sources - the library did not support this answer.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {sources.map((source, index) => (
            <li
              key={`${source.filename}-${index}`}
              id={sourceElementId(index, scope)}
              style={{
                border: "1px solid #e5e5e5",
                borderRadius: 4,
                padding: "0.5rem 0.75rem",
                scrollMarginTop: "1rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "baseline", gap: "0.4rem" }}>
                <span
                  style={{
                    fontSize: "0.75rem",
                    fontWeight: 700,
                    color: "#1a5fb4",
                    background: "#eaf1fb",
                    borderRadius: 4,
                    padding: "0 0.35rem",
                  }}
                >
                  {index + 1}
                </span>
                <span style={{ fontWeight: 600 }}>{source.filename}</span>
              </div>
              {source.summary && (
                <div style={{ fontSize: "0.85rem", color: "#444", marginTop: "0.2rem", fontStyle: "italic" }}>
                  {source.summary}
                </div>
              )}

              <dl style={{ margin: "0.35rem 0 0 0", fontSize: "0.85rem", color: "#666" }}>
                <div style={{ display: "flex", gap: "0.35rem" }}>
                  <dt style={{ fontWeight: 600 }}>Category:</dt>
                  <dd style={{ margin: 0 }}>{formatCategory(source.category)}</dd>
                </div>

                {source.section && (
                  <div style={{ display: "flex", gap: "0.35rem" }}>
                    <dt style={{ fontWeight: 600 }}>Section:</dt>
                    <dd style={{ margin: 0 }}>{source.section}</dd>
                  </div>
                )}

                {source.start_page && (
                  <div style={{ display: "flex", gap: "0.35rem" }}>
                    <dt style={{ fontWeight: 600 }}>Pages:</dt>
                    <dd style={{ margin: 0 }}>
                      {source.start_page}
                      {source.end_page && source.end_page !== source.start_page
                        ? `-${source.end_page}`
                        : ""}
                    </dd>
                  </div>
                )}

                <div style={{ display: "flex", gap: "0.35rem" }}>
                  <dt style={{ fontWeight: 600 }}>Relevance:</dt>
                  <dd style={{ margin: 0 }}>{source.score.toFixed(2)}</dd>
                </div>
              </dl>

              {source.excerpt && (
                <>
                  <button
                    type="button"
                    onClick={() => toggle(index)}
                    aria-expanded={openIndexes.has(index)}
                    style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}
                  >
                    {openIndexes.has(index) ? "Hide passage" : "Show passage"}
                  </button>
                  {openIndexes.has(index) && (
                    <blockquote
                      style={{
                        margin: "0.5rem 0 0 0",
                        padding: "0.5rem 0.75rem",
                        borderLeft: "3px solid #1a5fb4",
                        background: "#f7faff",
                        fontSize: "0.85rem",
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.45,
                      }}
                    >
                      {source.excerpt}
                    </blockquote>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
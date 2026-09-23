import type { OwnerResearchSource } from "@/lib/api/types";

interface SourcesPanelProps {
  sources: OwnerResearchSource[];
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
 * Only fields the backend actually returns are shown (filename,
 * category, section, page range, relevance score). The backend's
 * OwnerResearchSource model has no chunk id or excerpt text today, so
 * none is shown here - adding one would mean inventing data the
 * backend never sent.
 */
export function SourcesPanel({ sources }: SourcesPanelProps) {
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
              id={`source-${index}`}
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
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
import type { OwnerResearchSource } from "@/lib/api/types";

interface SourcesPanelProps {
  sources: OwnerResearchSource[];
}

/**
 * Renders exactly the `sources` array POST /research/ask returned -
 * every entry here traces to a chunk the backend's retrieval actually
 * found (citation lock is enforced server-side; this component only
 * displays what it's given, never invents or reorders around it).
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
              style={{ border: "1px solid #e5e5e5", borderRadius: 4, padding: "0.5rem 0.75rem" }}
            >
              <div style={{ fontWeight: 600 }}>{source.filename}</div>
              <div style={{ fontSize: "0.85rem", color: "#666" }}>
                {source.category}
                {source.section ? ` · Section ${source.section}` : ""}
                {source.start_page ? ` · p. ${source.start_page}${source.end_page && source.end_page !== source.start_page ? `-${source.end_page}` : ""}` : ""}
                {" · relevance "}
                {source.score.toFixed(2)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
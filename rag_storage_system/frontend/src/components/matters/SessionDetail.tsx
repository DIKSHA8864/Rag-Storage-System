import type { MatterIntakeSessionDetailResponse } from "@/lib/api/types";

interface SessionDetailProps {
  detail: MatterIntakeSessionDetailResponse;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Renders exactly what GET /admin/matters/{id}/intake-sessions/{id}
 * returned - the same real timeline, uploaded documents, recorded
 * facts, and reports the Client's own session view is built from.
 * Never invents or summarizes beyond what the backend sent.
 */
export function SessionDetail({ detail }: SessionDetailProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      <section>
        <h3 style={{ fontSize: "0.9rem", color: "#555" }}>Timeline</h3>
        {detail.timeline.length === 0 ? (
          <p style={{ color: "#777", fontSize: "0.85rem" }}>No events yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
            {detail.timeline.map((event) => (
              <li key={event.id} style={{ padding: "0.25rem 0", borderBottom: "1px solid #f0f0f0" }}>
                <strong>{event.event_type}</strong>: {event.description}
                <span style={{ color: "#999" }}> - {new Date(event.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 style={{ fontSize: "0.9rem", color: "#555" }}>Documents</h3>
        {detail.uploaded_inputs.length === 0 ? (
          <p style={{ color: "#777", fontSize: "0.85rem" }}>No documents uploaded yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
            {detail.uploaded_inputs.map((input) => (
              <li key={input.id} style={{ padding: "0.25rem 0" }}>
                📄 {input.original_filename} ({formatSize(input.size)}) - {input.processing_status}
                {input.status_detail && <span style={{ color: "#c0392b" }}> - {input.status_detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 style={{ fontSize: "0.9rem", color: "#555" }}>Facts</h3>
        {detail.facts.length === 0 ? (
          <p style={{ color: "#777", fontSize: "0.85rem" }}>No facts recorded yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
            {detail.facts.map((fact) => (
              <li key={fact.id} style={{ padding: "0.25rem 0" }}>
                <span style={{ color: "#999" }}>[{fact.category}]</span> {fact.fact_key}: {fact.fact_value}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 style={{ fontSize: "0.9rem", color: "#555" }}>Reports</h3>
        {detail.reports.length === 0 ? (
          <p style={{ color: "#777", fontSize: "0.85rem" }}>No reports generated yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
            {detail.reports.map((report) => (
              <li key={report.id} style={{ padding: "0.25rem 0" }}>
                Report #{report.id} ({report.format.toUpperCase()}) - {new Date(report.created_at).toLocaleString()}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
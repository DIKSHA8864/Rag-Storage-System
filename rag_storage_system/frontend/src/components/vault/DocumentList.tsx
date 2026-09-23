import type { DocumentInfo } from "@/lib/api/types";

interface DocumentListProps {
  documents: DocumentInfo[];
  onDelete: (filename: string) => void;
  deletingFilename: string | null;
}

const STATUS_COLORS: Record<string, { background: string; color: string }> = {
  Uploaded: { background: "#eaf1fb", color: "#1a5fb4" },
  Processing: { background: "#fff8e6", color: "#8a6116" },
  Embedding: { background: "#fff8e6", color: "#8a6116" },
  Indexed: { background: "#e8f5e9", color: "#2e7d32" },
  Failed: { background: "#fdecea", color: "#c0392b" },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Renders exactly the documents GET /documents returned for the
 * current folder - filename, size, extension, and the real
 * Uploaded/Processing/Embedding/Indexed/Failed status the backend's
 * processing pipeline set (app/metadata/models.py's DocumentStatus).
 * `status_detail`, when the backend sent one (currently only set on
 * Failed - see app/jobs/processing.py), is shown verbatim - never
 * invented or guessed at.
 */
export function DocumentList({ documents, onDelete, deletingFilename }: DocumentListProps) {
  if (documents.length === 0) {
    return <p style={{ color: "#777" }}>This folder has no documents yet.</p>;
  }

  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      {documents.map((doc) => {
        const statusStyle = STATUS_COLORS[doc.status] ?? { background: "#f0f0f0", color: "#555" };

        return (
          <li
            key={doc.relative_path}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "0.35rem",
              border: "1px solid #e5e5e5",
              borderRadius: 4,
              padding: "0.5rem 0.75rem",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 600 }}>📄 {doc.filename}</div>
                <div style={{ fontSize: "0.8rem", color: "#777" }}>
                  {doc.extension.replace(".", "").toUpperCase()} · {formatSize(doc.size)}
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span
                  style={{
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    padding: "0.15rem 0.5rem",
                    borderRadius: 4,
                    ...statusStyle,
                  }}
                >
                  {doc.status}
                </span>
                <button type="button" onClick={() => onDelete(doc.filename)} disabled={deletingFilename === doc.filename}>
                  {deletingFilename === doc.filename ? "Deleting..." : "Delete"}
                </button>
              </div>
            </div>

            {doc.status_detail && (
              <div
                style={{
                  fontSize: "0.8rem",
                  borderRadius: 4,
                  padding: "0.35rem 0.5rem",
                  ...statusStyle,
                }}
              >
                {doc.status_detail}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
import Link from "next/link";

import type { MatterInfo } from "@/lib/api/types";

interface MatterListProps {
  matters: MatterInfo[];
}

export function MatterList({ matters }: MatterListProps) {
  if (matters.length === 0) {
    return <p style={{ color: "#777" }}>No matters created yet.</p>;
  }

  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      {matters.map((matter) => (
        <li key={matter.id}>
          <Link
            href={`/matters/${matter.id}`}
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "0.5rem 0.75rem",
              border: "1px solid #e5e5e5",
              borderRadius: 4,
              textDecoration: "none",
              color: "inherit",
            }}
          >
            <span>
              {matter.name}
              <span style={{ marginLeft: "0.5rem", fontSize: "0.75rem", color: "#777" }}>
                {matter.kind === "case" ? "Case" : "Client"}
                {matter.client_email && matter.kind !== "case" ? ` - ${matter.client_email}` : ""}
              </span>
            </span>
            <span style={{ color: matter.is_active ? "#2e7d32" : "#999", fontSize: "0.85rem" }}>
              {matter.is_active ? "Active" : "Inactive"}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
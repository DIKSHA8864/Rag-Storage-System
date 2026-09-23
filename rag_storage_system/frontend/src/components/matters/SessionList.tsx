import type { IntakeSessionInfo } from "@/lib/api/types";

interface SessionListProps {
  sessions: IntakeSessionInfo[];
  selectedSessionId: number | null;
  onSelect: (sessionId: number) => void;
}

export function SessionList({ sessions, selectedSessionId, onSelect }: SessionListProps) {
  if (sessions.length === 0) {
    return <p style={{ color: "#777" }}>No intake sessions for this Matter yet.</p>;
  }

  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.35rem" }}>
      {sessions.map((session) => (
        <li key={session.id}>
          <button
            type="button"
            onClick={() => onSelect(session.id)}
            style={{
              display: "flex",
              justifyContent: "space-between",
              width: "100%",
              textAlign: "left",
              padding: "0.5rem 0.75rem",
              border: "1px solid #e5e5e5",
              borderRadius: 4,
              background: session.id === selectedSessionId ? "#eaf1fb" : "#fff",
            }}
          >
            <span>{session.title}</span>
            <span style={{ color: "#777", fontSize: "0.85rem" }}>{session.status}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
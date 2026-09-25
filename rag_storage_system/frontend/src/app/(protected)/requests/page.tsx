import { HandoffQueue } from "@/components/handoffs/HandoffQueue";

export default function RequestsPage() {
  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <h1>Talk-to-a-person requests</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        Clients who asked, during intake, to speak with someone at the firm. Take one, contact the client, then close it
        with a note.
      </p>
      <div style={{ marginTop: "1rem" }}>
        <HandoffQueue />
      </div>
    </div>
  );
}

import { QueryLog } from "@/components/activity/QueryLog";

export default function ActivityPage() {
  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <h1>Activity</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        Every question asked in your organization - who asked where, what the library returned, and whether it
        was answered. Use it to spot gaps in the library (&quot;No authority&quot;) and tune Settings.
      </p>
      <div style={{ marginTop: "1rem" }}>
        <QueryLog />
      </div>
    </div>
  );
}

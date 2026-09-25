import { AnalyticsDashboard } from "@/components/analytics/AnalyticsDashboard";

export default function AnalyticsPage() {
  return (
    <div style={{ maxWidth: 980, margin: "0 auto" }}>
      <h1>Analytics</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>Your organization only. Counted from the system&apos;s own records.</p>
      <div style={{ marginTop: "1rem" }}>
        <AnalyticsDashboard />
      </div>
    </div>
  );
}

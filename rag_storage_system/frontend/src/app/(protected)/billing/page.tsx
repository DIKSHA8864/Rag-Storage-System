import { BillingDashboard } from "@/components/billing/BillingDashboard";

export default function BillingPage() {
  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <h1>Billing &amp; Subscription</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        View this firm&apos;s current plan, subscription status, limits, and usage. Plan changes and
        cancellation require the Owner role.
      </p>
      <div style={{ marginTop: "1.5rem" }}>
        <BillingDashboard />
      </div>
    </div>
  );
}

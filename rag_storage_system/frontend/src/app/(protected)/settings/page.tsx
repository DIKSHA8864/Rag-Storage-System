import { SettingsForm } from "@/components/settings/SettingsForm";

export default function SettingsPage() {
  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <h1>Settings</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>These apply to your organization only.</p>
      <div style={{ marginTop: "1.5rem" }}>
        <SettingsForm />
      </div>
    </div>
  );
}

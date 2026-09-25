import { PleadingSettingsForm } from "@/components/settings/PleadingSettingsForm";
import { SettingsForm } from "@/components/settings/SettingsForm";
import { TemplateManager } from "@/components/settings/TemplateManager";

export default function SettingsPage() {
  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <h1>Settings</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>These apply to your organization only.</p>
      <div style={{ marginTop: "1.5rem" }}>
        <SettingsForm />
      </div>
      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "1.05rem" }}>Pleading details</h2>
        <p style={{ color: "#666", fontSize: "0.85rem" }}>
          Printed in the attorney block and caption of every generated complaint (California pleading paper). Blank
          fields stay as [BRACKETED] placeholders.
        </p>
        <PleadingSettingsForm />
      </section>
      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "1.05rem" }}>Pleading templates</h2>
        <TemplateManager />
      </section>
    </div>
  );
}

import { PromptManager } from "@/components/prompts/PromptManager";

export default function PromptsPage() {
  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <h1>Prompt Management</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        Edit and roll back the system prompts driving Claude-backed generation (client report narratives and research answers).
      </p>
      <div style={{ marginTop: "1.5rem" }}>
        <PromptManager />
      </div>
    </div>
  );
}

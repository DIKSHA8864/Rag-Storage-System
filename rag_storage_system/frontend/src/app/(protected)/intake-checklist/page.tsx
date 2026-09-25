import { ChecklistEditor } from "@/components/intake/ChecklistEditor";

export default function IntakeChecklistPage() {
  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <h1>Intake checklist</h1>
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        Every client tells their story first and answers follow-up questions drawn from your &quot;Question
        Frameworks&quot; library folder. Then they are asked these screening questions, the protected-activity
        questions, and key dates. Changes apply to new interviews in your organization only.
      </p>
      <div style={{ marginTop: "1.5rem" }}>
        <ChecklistEditor />
      </div>
    </div>
  );
}

interface AnswerPanelProps {
  answer: string;
  hasSupport: boolean;
}

/**
 * Renders the real answer text returned by POST /research/ask -
 * nothing here generates or alters that text. When hasSupport is
 * false (the backend's honest-gap path fired - see
 * app/analysis/answer_generation.py's stream_grounded_answer()), the
 * answer is styled as an explicit "library doesn't support this"
 * notice instead of a normal answer, so the honest-gap behavior stays
 * visible to the user rather than looking like an ordinary result.
 */
export function AnswerPanel({ answer, hasSupport }: AnswerPanelProps) {
  return (
    <section
      style={{
        border: "1px solid #d0d0d0",
        borderRadius: 6,
        padding: "1rem 1.25rem",
        background: hasSupport ? "#ffffff" : "#fff8e6",
        borderColor: hasSupport ? "#d0d0d0" : "#d9a441",
      }}
    >
      <h2 style={{ marginTop: 0, fontSize: "1rem", color: "#555" }}>Answer</h2>

      {!hasSupport && (
        <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.85rem", fontWeight: 600, color: "#8a6116" }}>
          No supporting material found in the library
        </p>
      )}

      <p style={{ margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{answer}</p>
    </section>
  );
}
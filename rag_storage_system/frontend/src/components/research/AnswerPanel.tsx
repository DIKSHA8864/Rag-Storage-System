import type { OwnerResearchSource } from "@/lib/api/types";
import { parseAnswerCitations } from "@/lib/research/citations";
import { openSourcePassage } from "./SourcesPanel";

interface AnswerPanelProps {
  answer: string;
  hasSupport: boolean;
  sources: OwnerResearchSource[];
}

/**
 * Renders the real answer text returned by POST /research/ask -
 * nothing here generates or alters that text. Inline "[filename]"
 * citations the backend wrote into the answer (see
 * app/analysis/answer_generation.py) are linked to their matching
 * card in the Sources panel when the filename matches one of
 * `sources` exactly - any bracketed text that doesn't match a real
 * source is left as plain text instead of becoming a fake link.
 *
 * When hasSupport is false (the backend's honest-gap path fired), the
 * answer is styled as an explicit "library doesn't support this"
 * notice instead of a normal answer, so that behavior stays visible.
 */
export function AnswerPanel({ answer, hasSupport, sources }: AnswerPanelProps) {
  const segments = parseAnswerCitations(answer, sources);

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

      <p style={{ margin: 0, whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
        {segments.map((segment, i) =>
          segment.type === "citation" && segment.sourceIndex !== undefined ? (
            <a
              key={i}
              href={`#source-${segment.sourceIndex}`}
              onClick={() => openSourcePassage(segment.sourceIndex as number)}
              title={sources[segment.sourceIndex]?.filename}
              style={{
                display: "inline-block",
                margin: "0 0.15rem",
                padding: "0 0.35rem",
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "#1a5fb4",
                background: "#eaf1fb",
                borderRadius: 4,
                textDecoration: "none",
              }}
            >
              [{segment.sourceIndex + 1}]
            </a>
          ) : (
            <span key={i}>{segment.text}</span>
          )
        )}
      </p>
    </section>
  );
}
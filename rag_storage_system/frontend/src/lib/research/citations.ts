import type { OwnerResearchSource } from "@/lib/api/types";

// Mirrors app/analysis/answer_generation.py's citation format and its
// tolerant match rule (_citations_are_grounded): every citation the
// backend writes into an answer is "[filename]" or
// "[filename - section]", and the backend already guarantees the
// filename names a real retrieved source. This only recognizes and
// links citations the backend already produced - it never invents a
// source or a match that isn't actually in `sources`.
const CITATION_PATTERN = /\[([^\[\]]+)\]/g;

export interface AnswerSegment {
  type: "text" | "citation";
  text: string;
  sourceIndex?: number;
}

export function parseAnswerCitations(
  answer: string,
  sources: OwnerResearchSource[]
): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let lastIndex = 0;

  for (const match of answer.matchAll(CITATION_PATTERN)) {
    const matchIndex = match.index ?? 0;
    const fullMatch = match[0];
    const label = match[1];

    if (matchIndex > lastIndex) {
      segments.push({ type: "text", text: answer.slice(lastIndex, matchIndex) });
    }

    const filename = label.split(" - ")[0].trim();
    const sourceIndex = sources.findIndex((source) => source.filename === filename);

    segments.push({
      type: "citation",
      text: fullMatch,
      sourceIndex: sourceIndex === -1 ? undefined : sourceIndex,
    });

    lastIndex = matchIndex + fullMatch.length;
  }

  if (lastIndex < answer.length) {
    segments.push({ type: "text", text: answer.slice(lastIndex) });
  }

  return segments;
}
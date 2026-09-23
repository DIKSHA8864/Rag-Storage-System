import type { ComplaintPreviewSection } from "@/lib/api/types";

interface ComplaintDraftPreviewProps {
  sections: ComplaintPreviewSection[];
}

export function ComplaintDraftPreview({ sections }: ComplaintDraftPreviewProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      {sections.map((section, index) => {
        const isAuthority = section.heading.includes("Cited Legal Authority");
        const isResearch = section.heading.includes("Research Suggestions");

        return (
          <section
            key={`${section.heading}-${index}`}
            style={{
              border: "1px solid #e5e5e5",
              borderRadius: 4,
              padding: "0.5rem 0.75rem",
              background: isAuthority ? "#eaf1fb" : isResearch ? "#fff8e6" : "#fff",
            }}
          >
            <h4 style={{ margin: "0 0 0.35rem 0", fontSize: "0.85rem", color: "#555" }}>{section.heading}</h4>
            {section.paragraphs.map((paragraph, paragraphIndex) => (
              <p key={paragraphIndex} style={{ margin: "0.25rem 0", fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>
                {paragraph}
              </p>
            ))}
          </section>
        );
      })}
    </div>
  );
}

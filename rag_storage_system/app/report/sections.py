"""
Flattens a StructuredReport into (heading, paragraphs) pairs - the
single content model every ReportRenderer (docx/pdf/image) consumes, so
the three output formats can never drift apart. Exact same pattern as
app/analysis/report_export.py's _report_sections(), generalized for
StructuredReport instead of the Phase 2 AnalysisReport dict.
"""

from app.report.schema import StructuredReport


def report_sections(report: StructuredReport) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = [
        ("Summary", [report.summary]),
    ]

    if report.timeline:
        sections.append(
            (
                "Timeline",
                [f"{entry.occurred_at} - {entry.event_type}: {entry.description}" for entry in report.timeline],
            )
        )

    if report.extracted_inputs:
        paragraphs = []
        for item in report.extracted_inputs:
            review_flag = " [REQUIRES ATTORNEY REVIEW - mock/placeholder extraction]" if item.requires_review else ""
            paragraphs.append(
                f"{item.original_filename} ({item.media_type}, {item.content_type}, via {item.provider})"
                f"{review_flag}: {item.text}"
            )
        sections.append(("Submitted Materials", paragraphs))

    sections.append(("Attorney Review Notice", [report.attorney_review_notice]))
    sections.append(("Disclaimer", [report.disclaimer_text]))

    return sections

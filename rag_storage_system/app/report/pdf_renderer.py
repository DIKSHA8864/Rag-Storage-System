"""PDF rendering for StructuredReport - same PyMuPDF Story/DocumentWriter approach as app/analysis/report_export.py's build_report_pdf()."""

import html
import io

import pymupdf

from app.report.renderer_base import ReportRenderer
from app.report.schema import StructuredReport
from app.report.sections import report_sections


class PdfReportRenderer(ReportRenderer):

    media_type = "application/pdf"
    file_extension = "pdf"

    def render(self, report: StructuredReport) -> bytes:
        html_parts = ["<h1>Client Intake Report</h1>"]
        for heading, paragraphs in report_sections(report):
            html_parts.append(f"<h2>{html.escape(heading)}</h2>")
            html_parts.extend(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)

        story = pymupdf.Story(html="".join(html_parts))
        mediabox = pymupdf.paper_rect("a4")
        where = mediabox + (36, 36, -36, -36)

        buffer = io.BytesIO()
        writer = pymupdf.DocumentWriter(buffer)

        more = 1
        while more:
            device = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(device)
            writer.end_page()

        writer.close()
        return buffer.getvalue()

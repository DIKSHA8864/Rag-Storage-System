"""Tests for app/report/{docx,pdf,image}_renderer.py - real rendering, no mocking of the renderers themselves."""

import io

import pytest
from docx import Document

from app.report.docx_renderer import DocxReportRenderer
from app.report.image_renderer import ImageReportRenderer
from app.report.pdf_renderer import PdfReportRenderer
from app.report.schema import ExtractedInputSummary, StructuredReport, TimelineEntry


def _sample_report() -> StructuredReport:
    return StructuredReport(
        intake_session_id=1,
        matter_name="Acme Corp",
        generated_at="2026-01-01T00:00:00+00:00",
        summary="SUMMARY-MARKER-TEXT",
        timeline=[
            TimelineEntry(
                event_type="session_created", description="Intake session created.",
                occurred_at="2026-01-01T00:00:00+00:00",
            )
        ],
        extracted_inputs=[
            ExtractedInputSummary(
                original_filename="scan.png", media_type="image", content_type="ocr_text",
                text="OCR-MARKER-TEXT", provider="mock", requires_review=True,
            )
        ],
        disclaimer_text="DISCLAIMER-MARKER-TEXT",
    )


def test_docx_renderer_contains_summary_and_disclaimer():
    content = DocxReportRenderer().render(_sample_report())

    document = Document(io.BytesIO(content))
    full_text = "\n".join(p.text for p in document.paragraphs)

    assert "SUMMARY-MARKER-TEXT" in full_text
    assert "OCR-MARKER-TEXT" in full_text
    assert "REQUIRES ATTORNEY REVIEW" in full_text
    assert "DISCLAIMER-MARKER-TEXT" in full_text


def test_pdf_renderer_contains_summary_and_disclaimer():
    pymupdf = pytest.importorskip("pymupdf")

    content = PdfReportRenderer().render(_sample_report())

    doc = pymupdf.open(stream=content, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)

    assert "SUMMARY-MARKER-TEXT" in full_text
    assert "DISCLAIMER-MARKER-TEXT" in full_text


def test_image_renderer_produces_a_readable_png_for_a_single_page_report():
    pytest.importorskip("pymupdf")

    renderer = ImageReportRenderer()
    content = renderer.render(_sample_report())

    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    assert renderer.media_type == "image/png"

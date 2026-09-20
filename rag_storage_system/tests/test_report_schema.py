"""Tests for app/report/schema.py and app/report/sections.py."""

from app.report.schema import ExtractedInputSummary, StructuredReport, TimelineEntry
from app.report.sections import report_sections


def _sample_report() -> StructuredReport:
    return StructuredReport(
        intake_session_id=1,
        matter_name="Acme Corp",
        generated_at="2026-01-01T00:00:00+00:00",
        summary="This intake session has 1 submitted item(s).",
        timeline=[
            TimelineEntry(
                event_type="session_created", description="Intake session created.",
                occurred_at="2026-01-01T00:00:00+00:00",
            )
        ],
        extracted_inputs=[
            ExtractedInputSummary(
                original_filename="scan.png", media_type="image", content_type="ocr_text",
                text="[MOCK OCR] ...", provider="mock", requires_review=True,
            )
        ],
        disclaimer_text="THE-DISCLAIMER",
    )


def test_structured_report_has_no_numeric_score_field():
    """AshiLegal rule: no numeric confidence/match score anywhere on an intake report."""

    assert "score" not in StructuredReport.model_fields


def test_structured_report_always_carries_a_disclaimer_and_review_notice():
    report = _sample_report()
    assert report.disclaimer_text == "THE-DISCLAIMER"
    assert "attorney" in report.attorney_review_notice.lower()


def test_report_sections_flags_mock_content_as_requiring_review():
    section_dict = dict(report_sections(_sample_report()))
    assert any("REQUIRES ATTORNEY REVIEW" in p for p in section_dict["Submitted Materials"])


def test_report_sections_always_ends_with_disclaimer():
    sections = report_sections(_sample_report())
    assert sections[-1] == ("Disclaimer", ["THE-DISCLAIMER"])


def test_report_sections_includes_timeline():
    section_dict = dict(report_sections(_sample_report()))
    assert any("session_created" in p for p in section_dict["Timeline"])

"""
ReportRenderer interface - StructuredReport -> {DOCX, PDF, Image}, no
duplicated rendering logic between formats (each renderer consumes the
same app/report/sections.py output). Mirrors the provider-interface
pattern used throughout this app (app/analysis/base.py,
app/multimodal/ocr.py, etc.).
"""

from abc import ABC, abstractmethod

from app.report.schema import StructuredReport


class ReportRenderer(ABC):
    """Abstract base class for all report renderers."""

    media_type: str
    file_extension: str

    @abstractmethod
    def render(self, report: StructuredReport) -> bytes:
        raise NotImplementedError

"""
Image rendering for StructuredReport - builds the same PDF
PdfReportRenderer produces, then rasterizes each page to PNG
(pymupdf's Pixmap.tobytes("png")) - zero new dependencies, since
pymupdf is already a project dependency. A single-page report returns
raw PNG bytes; a multi-page one returns a ZIP of page_1.png,
page_2.png, ... NOTE: media_type/file_extension are only accurate
AFTER render() has been called once (they reflect what the last
render() call actually produced).
"""

import io
import zipfile

import pymupdf

from app.report.pdf_renderer import PdfReportRenderer
from app.report.renderer_base import ReportRenderer
from app.report.schema import StructuredReport

_PNG_MEDIA_TYPE = "image/png"
_ZIP_MEDIA_TYPE = "application/zip"


class ImageReportRenderer(ReportRenderer):

    media_type = _PNG_MEDIA_TYPE
    file_extension = "png"

    def render(self, report: StructuredReport) -> bytes:
        pdf_bytes = PdfReportRenderer().render(report)

        pages_png: list[bytes] = []
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                pixmap = page.get_pixmap(dpi=150)
                pages_png.append(pixmap.tobytes("png"))

        if len(pages_png) == 1:
            self.media_type = _PNG_MEDIA_TYPE
            self.file_extension = "png"
            return pages_png[0]

        self.media_type = _ZIP_MEDIA_TYPE
        self.file_extension = "zip"

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for index, png_bytes in enumerate(pages_png, start=1):
                archive.writestr(f"page_{index}.png", png_bytes)

        return buffer.getvalue()

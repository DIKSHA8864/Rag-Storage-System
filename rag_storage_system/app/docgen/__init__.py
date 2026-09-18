"""
DOCUMENT GENERATION

Blueprint Section 2, non-negotiable: "Deliverables are produced as
finished, formatted, downloadable files (.docx and .pdf) - correctly
styled headings, numbering, captions - not as chat text to be
copy-pasted."

Phase 2 needs one document type: the research memo. Phase 3's intake
report and Phase 4's complaint will be siblings of memo_builder.py,
which is why input is a plain dict (a "structured JSON" document spec)
rather than anything answer-service-shaped: the model never formats a
document, it only supplies content that a builder here formats.

Both builders return bytes, so the API can stream them without writing
temp files.
"""

from app.docgen.memo_builder import build_memo_docx, build_memo_pdf  # noqa: F401
"""
Disclaimer shown to End Users - DB-backed (app/metadata/base.py's
get_disclaimer()/update_disclaimer(), implemented by both
SQLiteMetadataRepository and PostgresMetadataRepository) so the Owner
can edit it from the Admin Dashboard (PUT /admin/disclaimer,
app/api/storage_api.py) without a code change or restart.

Every DOCX/PDF export of an analysis report
(app/analysis/report_export.py) embeds whatever this currently
resolves to, so an Owner's edit shows up in the very next export.
"""

from app.metadata.base import MetadataRepository

DEFAULT_DISCLAIMER_TEXT = (
    "This report is generated automatically by comparing the submitted "
    "content against the configured knowledge base. It is provided for "
    "informational purposes only and does not constitute legal, "
    "financial, or professional advice. Verify all findings "
    "independently before relying on them."
)


def get_current_disclaimer_text(metadata_repository: MetadataRepository) -> str:
    """Return the Owner-edited disclaimer, or the default if none has been saved yet."""

    disclaimer = metadata_repository.get_disclaimer()
    return disclaimer["text"] if disclaimer else DEFAULT_DISCLAIMER_TEXT

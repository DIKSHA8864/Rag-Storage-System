"""
Strips control/null characters from free-text user input before it's
persisted or ever reaches a prompt. Pydantic's max_length already
bounds size (see app/api/schemas.py) and every query is parameterized
(no string-built SQL anywhere in this codebase) - this closes the one
remaining gap: a client embedding null bytes or ANSI/terminal control
sequences in text that later gets logged, rendered in
app/static/*.html, or written into a .docx/.pdf report.
"""

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(value: str) -> str:
    """Remove control characters, keeping normal whitespace (\\n, \\t) intact."""

    return _CONTROL_CHARS.sub("", value)
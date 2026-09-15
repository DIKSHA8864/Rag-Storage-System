import re


CHAPTER_PATTERN = re.compile(
    r"^\s*CHAPTER\s+([A-Z0-9IVXLC]+)\s*[:.\-]?\s*(.+)?$",
    re.IGNORECASE,
)

SECTION_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)+)\s*[.)]?\s+(.+?)\s*$"
)

LETTER_SECTION_PATTERN = re.compile(
    r"^\s*([A-Z])\.\s+(.+?)\s*$"
)


def detect_structure_line(line: str) -> dict | None:
    """
    Detect structural elements such as chapters,
    numbered sections, and lettered subsections.
    """

    if not line:
        return None

    text = line.strip()

    # Chapter
    chapter_match = CHAPTER_PATTERN.match(text)

    if chapter_match:
        return {
            "type": "chapter",
            "identifier": chapter_match.group(1),
            "title": (
                chapter_match.group(2).strip()
                if chapter_match.group(2)
                else ""
            ),
            "text": text,
        }

    # Numbered section
    section_match = SECTION_PATTERN.match(text)

    if section_match:
        identifier = section_match.group(1)
        title = section_match.group(2).strip()

        level = identifier.count(".") + 1

        return {
            "type": "section",
            "identifier": identifier,
            "title": title,
            "level": level,
            "text": text,
        }

    # Lettered subsection
    letter_match = LETTER_SECTION_PATTERN.match(text)

    if letter_match:
        return {
            "type": "subsection",
            "identifier": letter_match.group(1),
            "title": letter_match.group(2).strip(),
            "text": text,
        }

    return None
"""
Fills the firm's own Word template (their pleading paper, letterhead,
caption layout) with a PleadingContent.

The template is an ordinary .docx with placeholders written in double
braces anywhere - body, tables, headers, footers:

    {{attorney_block}}  attorney name/bar no., firm, address, phone, email, "Attorney for ..."
    {{court}}           e.g. SUPERIOR COURT OF THE STATE OF CALIFORNIA / FOR THE COUNTY OF LOS ANGELES
    {{plaintiff}}  {{defendant}}  {{case_number}}  {{title}}  {{causes}}
    {{body}}            required, on a paragraph of its own: the allegations, prayer and signature
                        are inserted there, each paragraph taking that paragraph's formatting

Anything else in braces is refused at upload, so a typo is caught then,
not in a filed document.
"""

import copy
import io
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Twips

from app.complaint.pleading import PleadingContent

KNOWN_PLACEHOLDERS = ("body", "attorney_block", "court", "plaintiff", "defendant", "case_number", "title", "causes")
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


class TemplateError(ValueError):
    pass


def _all_paragraphs(document):
    def from_container(container):
        for paragraph in container.paragraphs:
            yield paragraph
        for table in container.tables:
            for row in table.rows:
                for cell in row.cells:
                    yield from from_container(cell)

    yield from from_container(document)
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if part.is_linked_to_previous:
                continue
            yield from from_container(part)


def _open(data: bytes):
    try:
        return Document(io.BytesIO(data))
    except Exception as exc:
        raise TemplateError("This isn't a Word (.docx) file that can be opened.") from exc


def inspect_template(data: bytes) -> list[str]:
    """The placeholders the template uses (sorted). Raises TemplateError if it can't be used."""

    document = _open(data)
    found: set[str] = set()
    body_alone = False
    for paragraph in _all_paragraphs(document):
        names = _PLACEHOLDER.findall(paragraph.text)
        found.update(names)
        if "body" in names and paragraph.text.strip().replace(" ", "") == "{{body}}":
            body_alone = True

    unknown = sorted(found - set(KNOWN_PLACEHOLDERS))
    if unknown:
        raise TemplateError(
            f"Unknown placeholder(s): {', '.join('{{' + n + '}}' for n in unknown)}. "
            f"Use only: {', '.join('{{' + n + '}}' for n in KNOWN_PLACEHOLDERS)}."
        )
    if "body" not in found:
        raise TemplateError("The template needs a {{body}} placeholder where the complaint's text goes.")
    if not body_alone:
        raise TemplateError("{{body}} must be on a paragraph of its own.")
    return sorted(found)


def _replace_inline(paragraph, values: dict[str, str]) -> None:
    text = paragraph.text
    if "{{" not in text:
        return
    replaced = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    if replaced == text:
        return
    runs = paragraph.runs
    # Word often splits "{{plaintiff}}" across several runs - keep the first run's formatting for the whole text.
    runs[0].text = replaced  # "\n" becomes a line break
    for run in runs[1:]:
        run.text = ""


def _insert_before(anchor, text: str, kind: str):
    new_p = copy.deepcopy(anchor._p)
    for child in list(new_p):
        if child.tag != anchor._p.get_or_add_pPr().tag:
            new_p.remove(child)
    anchor._p.addprevious(new_p)

    from docx.text.paragraph import Paragraph

    paragraph = Paragraph(new_p, anchor._parent)
    run = paragraph.add_run(text)
    template_runs = anchor.runs
    if template_runs and template_runs[0]._r.rPr is not None:
        run._r.insert(0, copy.deepcopy(template_runs[0]._r.rPr))

    fmt = paragraph.paragraph_format
    if kind == "heading":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fmt.first_line_indent = Twips(0)
        run.bold = True
        fmt.keep_with_next = True
    elif kind == "subheading":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fmt.first_line_indent = Twips(0)
        fmt.keep_with_next = True
    elif kind == "signature":
        fmt.left_indent = Twips(5040)
        fmt.first_line_indent = Twips(0)
        fmt.keep_with_next = True
    elif fmt.first_line_indent is None:
        fmt.first_line_indent = Twips(720)
    return paragraph


def fill_template(data: bytes, content: PleadingContent) -> bytes:
    document = _open(data)
    values = content.placeholder_values()

    body_paragraph = None
    for paragraph in list(_all_paragraphs(document)):
        if paragraph.text.strip().replace(" ", "") == "{{body}}" and body_paragraph is None:
            body_paragraph = paragraph
            continue
        _replace_inline(paragraph, values)
    if body_paragraph is None:
        raise TemplateError("The template has no {{body}} paragraph.")

    for block in content.body:
        text = f"{block.number}.\t{block.text}" if block.kind == "numbered" else block.text
        _insert_before(body_paragraph, text, block.kind)

    if content.attorney_notes:
        page_break = _insert_before(body_paragraph, "", "text")
        page_break.runs[0].add_break(WD_BREAK.PAGE)
        _insert_before(body_paragraph, "ATTORNEY NOTES - NOT PART OF THE PLEADING - REMOVE BEFORE FILING", "heading")
        for heading, paragraphs in content.attorney_notes:
            _insert_before(body_paragraph, heading, "subheading")
            for text in paragraphs:
                _insert_before(body_paragraph, text, "text")

    body_paragraph._p.getparent().remove(body_paragraph._p)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()

"""DOCX (python-docx): body paragraphs and tables in document order. Styles give the structure: ``Title`` /
``Heading N`` -> headings, ``List ...`` styles or numbering -> list items, small print -> notes. Vertically merged
table cells repeat their text (python-docx returns the merged cell for every row it spans)."""

import io
import re
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from hmap.agents.doc_intel.loaders.base import TOTAL_LINE_RE, Loaded, RawBlock, clean_spaces, rows_to_markdown

HEADING_STYLE_RE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


def _paragraph_block(p: Paragraph) -> RawBlock | None:
    text = clean_spaces(p.text)
    if not text:
        return None
    style = (p.style.name if p.style is not None else "") or ""
    m = HEADING_STYLE_RE.match(style)
    if m:
        return RawBlock("heading", text, level=int(m.group(1)))
    if style.lower() == "title":
        return RawBlock("heading", text, level=1)
    ppr = p._p.pPr
    if style.lower().startswith("list") or (ppr is not None and ppr.numPr is not None):
        return RawBlock("list_item", text)
    sizes = [r.font.size.pt for r in p.runs if r.font.size is not None]
    if sizes and max(sizes) <= 8.5:
        return RawBlock("note", text)
    if p.runs and all(r.bold for r in p.runs if r.text.strip()) and len(text) < 100 and not text.endswith(".") \
            and not TOTAL_LINE_RE.search(text):
        return RawBlock("heading", text, level=3)
    return RawBlock("paragraph", text)


def _table_rows(table: Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        seen: list[Any] = []
        for cell in row.cells:
            # a horizontally merged cell appears several times in the same row: keep it once
            if any(cell._tc is s for s in seen):
                cells.append("")
                continue
            seen.append(cell._tc)
            cells.append(clean_spaces(cell.text))
        rows.append(cells)
    return [r for r in rows if any(r)]


def load_docx(data: bytes) -> Loaded:
    loaded = Loaded(kind="docx")
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # not a valid .docx (e.g. an old binary .doc renamed)
        loaded.warnings.append(f"could not open the DOCX file: {type(exc).__name__}")
        return loaded
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            block = _paragraph_block(Paragraph(child, doc))
            if block is not None:
                loaded.blocks.append(block)
        elif tag == "tbl":
            rows = _table_rows(Table(child, doc))
            if rows:
                loaded.blocks.append(RawBlock("table", rows_to_markdown(rows), rows=rows))
    return loaded

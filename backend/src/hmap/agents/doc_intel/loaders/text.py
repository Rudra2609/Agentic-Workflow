"""Plain text and Markdown (also used for the vision model's page transcriptions, which are asked for Markdown)."""

import re

from hmap.agents.doc_intel.loaders.base import (
    BULLET_RE,
    NUMBER_RE,
    Loaded,
    RawBlock,
    clean_spaces,
    join_lines,
    rows_to_markdown,
)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
FENCE_RE = re.compile(r"^\s*```")


def _table_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [clean_spaces(c.replace("**", "")) for c in cells]


def parse_markdown(text: str, *, page: int | None = None, ocr: bool = False) -> list[RawBlock]:
    """Headings (``#``), list items (``-``, ``*``, ``1.``), pipe tables and paragraphs separated by blank lines.
    Plain text without Markdown comes out as paragraphs and list items."""
    blocks: list[RawBlock] = []
    para: list[str] = []
    item: list[str] | None = None
    table: list[list[str]] = []

    def flush() -> None:
        nonlocal item, table
        if para:
            blocks.append(RawBlock("paragraph", join_lines(para), page=page, ocr=ocr))
            para.clear()
        if item is not None:
            blocks.append(RawBlock("list_item", join_lines(item), page=page, ocr=ocr))
            item = None
        if table:
            blocks.append(RawBlock("table", rows_to_markdown(table), page=page, rows=table, ocr=ocr))
            table = []

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if FENCE_RE.match(line):
            continue
        if not line.strip():
            flush()
            continue
        if line.lstrip().startswith("|") and line.count("|") >= 2:
            if para or item is not None:  # a table right after text (no blank line); the table is still empty
                flush()
            if not TABLE_SEP_RE.match(line):
                table.append(_table_row(line))
            continue
        if table:
            flush()
        heading = HEADING_RE.match(line)
        if heading:
            flush()
            title = clean_spaces(heading.group(2).replace("**", ""))
            if title:
                blocks.append(RawBlock("heading", title, page=page, level=len(heading.group(1)), ocr=ocr))
            continue
        bullet = BULLET_RE.match(line) or NUMBER_RE.match(line)
        if bullet:
            flush()
            item = [line[bullet.end():]]
            continue
        if item is not None and raw[:1] in (" ", "\t"):  # indented continuation of a list item
            item.append(line)
            continue
        if item is not None:
            flush()
        para.append(line.replace("**", ""))
    flush()
    return blocks


def load_text(data: bytes) -> Loaded:
    text = data.decode("utf-8", errors="replace")
    loaded = Loaded(kind="text", blocks=parse_markdown(text))
    if "\ufffd" in text:
        loaded.warnings.append("some characters could not be decoded as UTF-8")
    return loaded

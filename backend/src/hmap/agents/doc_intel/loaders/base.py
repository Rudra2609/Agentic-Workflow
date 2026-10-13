"""What every loader produces: an ordered list of :class:`RawBlock` per document (before ids and section paths are
assigned by ``structure.py``), plus page info and warnings."""

import re
from dataclasses import dataclass, field

from hmap.agents.doc_intel.model import BBox, BlockType, PageInfo

# list markers: bullets, or a number / letter followed by "." or ")" (or a bare number before a capital letter)
BULLET_RE = re.compile(r"^\s*(?:[\u2022\u00b7\u25aa\u25e6\u2023\u2013\u2014*\-\uf0b7]\s+|\(cid:\d+\)\s*)(?=\S)")
NUMBER_RE = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|\(?[a-hA-H][.)]|\d{1,2}(?=\s+[A-Z]))\s+")
# section numbers in headings ("2.", "2.1", "Part A:")
HEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+")


def strip_marker(text: str) -> tuple[str, bool]:
    """Remove a leading list marker; returns (text, had_marker)."""
    for pattern in (BULLET_RE, NUMBER_RE):
        m = pattern.match(text)
        if m:
            return text[m.end():].strip(), True
    return text.strip(), False


CID_RE = re.compile(r"\(cid:\d+\)")
TOTAL_LINE_RE = re.compile(r"\b(total|marks?|points?)\b.*\d|\d.*\b(marks?|points?)\b", re.IGNORECASE)


def clean_spaces(text: str) -> str:
    """Collapse whitespace (incl. line breaks inside table cells)."""
    return re.sub(r"\s+", " ", text).strip()


def drop_cids(text: str) -> str:
    """pdfminer writes glyphs it cannot map as ``(cid:N)``; at the start of a line they are bullets."""
    return clean_spaces(CID_RE.sub(" ", text))


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines; undo end-of-line hyphenation ("require-" + "ment" -> "requirement")."""
    out = ""
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        if out.endswith("-") and line[:1].islower() and not out.endswith(" -"):
            out = out[:-1] + line
        else:
            out = f"{out} {line}" if out else line
    return clean_spaces(out)


def rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [[clean_spaces(c or "").replace("|", "/") for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)


@dataclass
class RawBlock:
    type: BlockType
    text: str
    page: int | None = None
    bbox: BBox | None = None
    level: int | None = None
    rows: list[list[str]] | None = None   # tables only
    ocr: bool = False
    size: float = 0.0                     # font size (PDF) or relative line height (OCR); for heading levels


@dataclass
class Loaded:
    kind: str                              # pdf | docx | text | image
    blocks: list[RawBlock] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

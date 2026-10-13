"""Native PDF text with positions (pdfplumber) and page rendering for OCR (pypdfium2).

Per page: words -> lines (split at wide gaps, so two columns never merge) -> blocks. Lines in the top/bottom margin
in small print are page furniture (header/footer); small print elsewhere is a note; larger or bold short lines are
headings; list markers start list items. Tables found by pdfplumber are cut out of the text and kept as rows.
A page with almost no text layer is rendered at ``OCR_DPI`` and handed back for OCR (``Loaded.pages[i].ocr``).
"""

import io
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any, cast

import pdfplumber
import pypdfium2 as pdfium

from hmap.agents.doc_intel.loaders.base import (
    BULLET_RE,
    NUMBER_RE,
    TOTAL_LINE_RE,
    Loaded,
    RawBlock,
    clean_spaces,
    drop_cids,
    join_lines,
    rows_to_markdown,
)
from hmap.agents.doc_intel.model import BlockType, PageInfo

MIN_TEXT_CHARS = 25          # fewer characters than this on a page -> treat it as scanned (OCR gate)
OCR_DPI = 200
MARGIN_FRACTION = 0.075      # top/bottom band where running headers/footers live


@dataclass
class _Line:
    words: list[dict[str, Any]]
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bold: bool
    col: int = 0

    @property
    def text(self) -> str:
        return clean_spaces(" ".join(w["text"] for w in self.words))


def _lines(words: list[dict[str, Any]]) -> list[_Line]:
    rows: list[list[dict[str, Any]]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[_Line] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        seg: list[dict[str, Any]] = [row[0]]
        for w in row[1:]:
            gap = w["x0"] - seg[-1]["x1"]
            if gap > 3.0 * max(float(seg[-1].get("size", 10)), 6.0):  # a column gutter, not a word space
                out.append(_make_line(seg))
                seg = [w]
            else:
                seg.append(w)
        out.append(_make_line(seg))
    return out


def _make_line(words: list[dict[str, Any]]) -> _Line:
    sizes = [float(w.get("size", 0)) for w in words]
    bold = sum(len(w["text"]) for w in words if "bold" in str(w.get("fontname", "")).lower())
    total = sum(len(w["text"]) for w in words) or 1
    return _Line(words=words, x0=min(w["x0"] for w in words), x1=max(w["x1"] for w in words),
                 top=min(w["top"] for w in words), bottom=max(w["bottom"] for w in words),
                 size=statistics.median(sizes) if sizes else 0.0, bold=bold / total > 0.6)


def _two_columns(lines: list[_Line], width: float) -> bool:
    mid = width / 2
    crossing = sum(1 for ln in lines if ln.x0 < mid - 10 and ln.x1 > mid + 10)
    right = sum(1 for ln in lines if ln.x0 >= mid - 5)
    return right >= 3 and crossing <= max(1, len(lines) // 15)


def _inside(word: dict[str, Any], boxes: list[tuple[float, float, float, float]]) -> bool:
    cx, cy = (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2
    return any(x0 - 1 <= cx <= x1 + 1 and top - 1 <= cy <= bottom + 1 for x0, top, x1, bottom in boxes)


def _norm(bbox: tuple[float, float, float, float], w: float, h: float) -> tuple[float, float, float, float]:
    x0, top, x1, bottom = bbox
    return (round(x0 / w, 4), round(top / h, 4), round(x1 / w, 4), round(bottom / h, 4))


def _page_blocks(page: Any, number: int, body_size: float) -> list[RawBlock]:
    width, height = float(page.width), float(page.height)
    tables = page.find_tables()
    boxes = [tuple(t.bbox) for t in tables]
    words = [w for w in page.extract_words(extra_attrs=["fontname", "size"], x_tolerance=1.5, y_tolerance=2)
             if not _inside(w, boxes)]
    lines = _lines(words)
    two_col = _two_columns(lines, width)
    for ln in lines:
        ln.col = 1 if two_col and ln.x0 >= width / 2 - 5 else 0

    items: list[tuple[int, float, Any]] = [(ln.col, ln.top, ln) for ln in lines]
    for table in tables:
        x0, top, _, _ = table.bbox
        items.append((1 if two_col and x0 >= width / 2 - 5 else 0, top, table))
    items.sort(key=lambda it: (it[0], it[1]))

    blocks: list[RawBlock] = []
    current: list[_Line] = []
    kind = "paragraph"

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = join_lines([ln.text for ln in current])
        if kind == "list_item":
            for pattern in (BULLET_RE, NUMBER_RE):
                m = pattern.match(text)
                if m:
                    text = text[m.end():]
                    break
        text = drop_cids(text)
        box = (min(ln.x0 for ln in current), min(ln.top for ln in current),
               max(ln.x1 for ln in current), max(ln.bottom for ln in current))
        size = statistics.median(ln.size for ln in current)
        if text.strip():
            blocks.append(RawBlock(cast(BlockType, kind), text.strip(), page=number, bbox=_norm(box, width, height),
                                   size=size))
        current = []

    for _, _, obj in items:
        if not isinstance(obj, _Line):
            flush()
            rows = [[drop_cids(c or "") for c in row] for row in obj.extract()]
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append(RawBlock("table", rows_to_markdown(rows), page=number,
                                       bbox=_norm(tuple(obj.bbox), width, height), rows=rows))
            continue
        ln = obj
        text = ln.text
        small = bool(ln.size) and ln.size < body_size * 0.86
        is_marker = bool(BULLET_RE.match(text) or NUMBER_RE.match(text))
        in_margin = ln.top < height * MARGIN_FRACTION or ln.bottom > height * (1 - MARGIN_FRACTION)
        if in_margin and (small or len(text) < 80):
            line_kind = "header" if ln.top < height / 2 else "footer"
        elif small:
            line_kind = "note"
        elif not TOTAL_LINE_RE.search(text) and not text.endswith(".") and (
                (ln.size >= body_size * 1.12 and len(text) < 150) or (ln.bold and len(text) < 100 and not is_marker)):
            line_kind = "heading"
        elif is_marker:
            line_kind = "list_start"
        else:
            line_kind = "text"

        prev = current[-1] if current else None
        gap = (ln.top - prev.bottom) if prev else 0.0
        same_flow = prev is not None and prev.col == ln.col and -2 <= gap <= max(ln.size, 6.0) * 0.9
        if line_kind == "heading" and kind == "heading" and prev is not None and same_flow \
                and abs(prev.size - ln.size) < 0.6:
            current.append(ln)  # a heading wrapped over two lines
        elif line_kind in ("header", "footer", "heading"):
            flush()
            kind = line_kind
            current = [ln]
            if line_kind != "heading":
                flush()
                kind = "paragraph"
        elif kind == "heading":
            flush()
            kind = "list_item" if line_kind == "list_start" else ("note" if line_kind == "note" else "paragraph")
            current = [ln]
        elif line_kind == "list_start":
            flush()
            kind = "list_item"
            current = [ln]
        elif line_kind == "note":
            if not (kind == "note" and same_flow):
                flush()
                kind = "note"
            current.append(ln)
        else:
            if not same_flow or kind == "note":
                flush()
                kind = "paragraph"
            current.append(ln)
    flush()
    return blocks


def render_page_png(data: bytes, page_number: int, dpi: int = OCR_DPI) -> bytes:
    pdf = pdfium.PdfDocument(data)
    try:
        image = pdf[page_number - 1].render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        image.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    finally:
        pdf.close()


def load_pdf(data: bytes) -> Loaded:
    """Synchronous (run it in a thread). Pages that need OCR get ``PageInfo.ocr=True`` and no blocks yet."""
    loaded = Loaded(kind="pdf")
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # corrupt or encrypted file
        loaded.warnings.append(f"could not open the PDF: {type(exc).__name__}")
        return loaded
    with pdf:
        sizes: Counter[float] = Counter()
        for page in pdf.pages:
            for ch in page.chars:
                sizes[round(float(ch.get("size", 0)), 1)] += 1
        body_size = sizes.most_common(1)[0][0] if sizes else 10.0
        for number, page in enumerate(pdf.pages, start=1):
            chars = len([c for c in page.chars if c.get("text", "").strip()])
            info = PageInfo(number=number, width=float(page.width), height=float(page.height), text_chars=chars)
            loaded.pages.append(info)
            if chars < MIN_TEXT_CHARS:
                info.ocr = True
                continue
            loaded.blocks.extend(_page_blocks(page, number, body_size))
    return loaded

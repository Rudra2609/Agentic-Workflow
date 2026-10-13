"""Normalisation (spec item 2.2): loader output -> :class:`SourceDocument` with block ids, heading levels, section
paths, table models and character offsets into one document text."""

from hmap.agents.doc_intel.loaders import InputDocument, Loaded, RawBlock
from hmap.agents.doc_intel.loaders.base import HEADING_NUMBER_RE
from hmap.agents.doc_intel.model import Block, SourceDocument, TableModel
from hmap.agents.doc_intel.tables import read_table

SEPARATOR = "\n\n"


def _assign_levels(blocks: list[RawBlock]) -> None:
    """Headings without a level (PDF, Tesseract) get one from their size rank; within one size, deeper numbering
    ("1.2" under "1") goes one level down per extra number."""
    sizes = sorted({round(b.size * 2) / 2 for b in blocks if b.type == "heading" and b.level is None and b.size},
                   reverse=True)
    rank = {s: i + 1 for i, s in enumerate(sizes)}

    def depth(b: RawBlock) -> int:
        m = HEADING_NUMBER_RE.match(b.text)
        return m.group(1).strip(".").count(".") + 1 if m else 0

    todo = [b for b in blocks if b.type == "heading" and b.level is None]
    shallowest: dict[int, int] = {}
    for b in todo:
        r, d = rank.get(round(b.size * 2) / 2, len(rank) + 1), depth(b)
        if d:
            shallowest[r] = min(shallowest.get(r, d), d)
    for b in todo:
        r, d = rank.get(round(b.size * 2) / 2, len(rank) + 1), depth(b)
        b.level = r * 10 + (d - shallowest.get(r, d) if d else 0)  # spaced out, closed up below
    levels = sorted({b.level for b in blocks if b.type == "heading" and b.level is not None})
    remap = {lv: i + 1 for i, lv in enumerate(levels)}  # close gaps: 2,3 -> 1,2
    for b in blocks:
        if b.type == "heading" and b.level is not None:
            b.level = remap[b.level]


def build_document(doc: InputDocument, loaded: Loaded, kind: str | None = None) -> SourceDocument:
    _assign_levels(loaded.blocks)
    out = SourceDocument(doc_id=doc.doc_id, name=doc.name, folder=doc.folder, path=doc.path,
                         media_type=doc.media_type, kind=kind or loaded.kind,
                         pages=loaded.pages, warnings=list(loaded.warnings))
    stack: list[tuple[int, str]] = []
    parts: list[str] = []
    offset = 0
    for n, raw in enumerate(loaded.blocks, start=1):
        if raw.type == "heading":
            level = raw.level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, raw.text))
            path = [t for _, t in stack]
        else:
            path = [t for _, t in stack]
        block = Block(id=f"b{n}", type=raw.type, text=raw.text, page=raw.page, bbox=raw.bbox, level=raw.level,
                      section_path=path, char_start=offset, char_end=offset + len(raw.text), ocr=raw.ocr)
        if raw.type == "table" and raw.rows:
            table = TableModel(id=f"t{len(out.tables) + 1}", block_id=block.id, page=raw.page, bbox=raw.bbox,
                               rows=raw.rows, section_path=path)
            table.kind = read_table(raw.rows).kind
            block.table_id = table.id
            out.tables.append(table)
        out.blocks.append(block)
        parts.append(raw.text)
        offset += len(raw.text) + len(SEPARATOR)
    out.text = SEPARATOR.join(parts)
    return out

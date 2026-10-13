"""Section-aligned chunks within a token budget (spec item 2.4).

The budget fits every model the ``reasoner`` role may land on: Gemini (large context), Groq (8K tokens per minute per
key on the free tier) and the local ``qwen3.5:9b``. Marks / rubric / deliverables tables are read by rules
(``tables.py``), and headers, footers and footnotes never carry requirements, so none of them is sent to the model.
"""

from dataclasses import dataclass, field

from hmap.agents.doc_intel.model import Block, SourceDocument

DEFAULT_BUDGET_TOKENS = 1200  # input; leaves room for a long answer (and hidden reasoning) within max_tokens
SKIP_TYPES = frozenset({"header", "footer", "note"})


def estimate_tokens(text: str) -> int:
    """~4 characters per token for English prose (good enough for budgeting; the gateway has no tokenizer)."""
    return max(1, len(text) // 4)


@dataclass
class Chunk:
    index: int
    doc_index: int
    document: SourceDocument
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        """What the model sees: a header line, then headings as Markdown and list items as "- " lines."""
        doc = self.document
        lines = [f"Document: {doc.name}" + (f" (folder: {doc.folder})" if doc.folder else "")]
        shown: list[str] = []
        for b in self.blocks:
            if b.type != "heading" and b.section_path and b.section_path != shown:
                missing = [h for h in b.section_path if h not in shown]
                for depth, title in enumerate(b.section_path, start=1):
                    if title in missing:
                        lines.append(f"{'#' * min(depth, 6)} {title}")
                shown = list(b.section_path)
            if b.type == "heading":
                lines.append(f"{'#' * min(b.level or 1, 6)} {b.text}")
                shown = list(b.section_path)
            elif b.type == "list_item":
                lines.append(f"- {b.text}")
            else:
                lines.append(b.text)
        return "\n".join(lines)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def _content(doc: SourceDocument) -> list[Block]:
    table_kinds = {t.id: t.kind for t in doc.tables}
    return [b for b in doc.blocks if b.type not in SKIP_TYPES
            and not (b.type == "table" and table_kinds.get(b.table_id or "", "other") != "other")]


def _sections(blocks: list[Block]) -> list[list[Block]]:
    """Split at every heading (a heading starts its own group with the blocks under it)."""
    groups: list[list[Block]] = []
    for b in blocks:
        if b.type == "heading" or not groups:
            groups.append([b])
        else:
            groups[-1].append(b)
    return groups


def make_chunks(docs: list[SourceDocument], budget: int = DEFAULT_BUDGET_TOKENS) -> list[Chunk]:
    """Whole sections are packed into a chunk while they fit; a new chunk starts at a section boundary; only a single
    section larger than the budget is split between blocks. Chunks never span documents."""
    chunks: list[Chunk] = []
    for doc_index, doc in enumerate(docs):
        current: Chunk | None = None
        for section in _sections(_content(doc)):
            if current is not None and Chunk(0, doc_index, doc, current.blocks + section).tokens > budget:
                current = None
            for block in section:
                if current is None:
                    current = Chunk(len(chunks), doc_index, doc)
                    chunks.append(current)
                current.blocks.append(block)
                if current.tokens > budget and len(current.blocks) > 1:
                    current.blocks.pop()
                    current = Chunk(len(chunks), doc_index, doc, [block])
                    chunks.append(current)
    kept = [c for c in chunks if any(b.type != "heading" for b in c.blocks)]
    for i, c in enumerate(kept):
        c.index = i
    return kept

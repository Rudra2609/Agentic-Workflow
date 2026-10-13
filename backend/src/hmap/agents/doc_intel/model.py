"""``DocumentModel``: the normalised view of every uploaded document (spec §4), stored as the ``document-model``
artifact so the UI can show each requirement's source and highlight it.

Coordinates: ``bbox`` is ``(x0, top, x1, bottom)`` as fractions of the page width/height (0..1), so the UI can draw it
over a page image of any size. Text offsets (``char_start``/``char_end``) index ``SourceDocument.text``.
"""

from typing import Literal

from pydantic import BaseModel, Field

BlockType = Literal["heading", "paragraph", "list_item", "table", "note", "header", "footer"]
BBox = tuple[float, float, float, float]
TableKind = Literal["marks", "rubric", "deliverables", "other"]

# blocks that never carry requirements (page furniture and small print)
NON_CONTENT: frozenset[str] = frozenset({"header", "footer"})


class Block(BaseModel):
    id: str
    type: BlockType
    text: str
    page: int | None = None
    bbox: BBox | None = None
    level: int | None = Field(default=None, description="heading level (1 = top)")
    section_path: list[str] = Field(default_factory=list)
    char_start: int = 0
    char_end: int = 0
    table_id: str | None = None
    ocr: bool = False


class TableModel(BaseModel):
    id: str
    block_id: str
    page: int | None = None
    bbox: BBox | None = None
    rows: list[list[str]]
    section_path: list[str] = Field(default_factory=list)
    kind: TableKind = "other"


class PageInfo(BaseModel):
    number: int
    width: float = 0.0
    height: float = 0.0
    ocr: bool = False
    ocr_engine: str | None = None          # "vision" | "tesseract" | None
    ocr_confidence: float | None = None    # tesseract mean word confidence 0..1
    text_chars: int = 0


class SourceDocument(BaseModel):
    doc_id: str = Field(description="artifact id of the uploaded file")
    name: str
    folder: str | None = None
    path: str | None = None
    media_type: str = ""
    kind: Literal["pdf", "docx", "text", "image"] = "text"
    pages: list[PageInfo] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    tables: list[TableModel] = Field(default_factory=list)
    text: str = ""
    warnings: list[str] = Field(default_factory=list)

    def block(self, block_id: str) -> Block | None:
        return next((b for b in self.blocks if b.id == block_id), None)


class ExtractionInfo(BaseModel):
    """How the set was made (shown in the UI's developer mode and kept for audits)."""

    chunks: int = 0
    llm_chunks: int = 0
    rules_only_chunks: int = 0
    answered_by: dict[str, int] = Field(default_factory=dict, description="provider:model -> chunks it answered")
    quotes: dict[str, int] = Field(default_factory=dict, description="exact / approximate / unverified")
    ocr_pages: dict[str, int] = Field(default_factory=dict, description="OCR engine -> pages read")
    prompt_version: str = ""


class DocumentModel(BaseModel):
    project_id: str
    documents: list[SourceDocument] = Field(default_factory=list)
    extraction: ExtractionInfo = Field(default_factory=ExtractionInfo)

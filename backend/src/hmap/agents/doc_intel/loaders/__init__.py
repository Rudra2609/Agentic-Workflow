"""Loaders (spec item 2.1): PDF (native or scanned), DOCX, text / Markdown and images, with per-page OCR gating."""

import asyncio
import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from PIL import Image

from hmap.agents.doc_intel.loaders.base import Loaded, RawBlock
from hmap.agents.doc_intel.loaders.docx import load_docx
from hmap.agents.doc_intel.loaders.pdf import load_pdf, render_page_png
from hmap.agents.doc_intel.loaders.text import load_text, parse_markdown
from hmap.agents.doc_intel.model import PageInfo

if TYPE_CHECKING:  # ocr.py imports the loaders' helpers: a runtime import here would be circular
    from hmap.agents.doc_intel.ocr import OcrEngine

PageProgress = Callable[[int, int], Awaitable[None]]  # (page done, pages total)


@dataclass
class InputDocument:
    doc_id: str
    name: str
    data: bytes
    media_type: str = ""
    folder: str | None = None
    path: str | None = None


def detect_kind(name: str, media_type: str, data: bytes) -> str:
    head = data[:8]
    suffix = PurePosixPath(name.lower()).suffix
    if head.startswith(b"%PDF") or media_type == "application/pdf":
        return "pdf"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff") or media_type.startswith("image/"):
        return "image"
    if head.startswith(b"PK") and (suffix == ".docx" or "wordprocessingml" in media_type):
        return "docx"
    return "text"


async def load_document(doc: InputDocument, ocr: "OcrEngine", on_page: PageProgress | None = None) -> Loaded:
    kind = detect_kind(doc.name, doc.media_type, doc.data)
    if kind == "docx":
        return await asyncio.to_thread(load_docx, doc.data)
    if kind == "text":
        return load_text(doc.data)
    if kind == "image":
        return await _load_image(doc.data, ocr)
    loaded = await asyncio.to_thread(load_pdf, doc.data)
    total = len(loaded.pages)
    for info in loaded.pages:
        if info.ocr:
            png = await asyncio.to_thread(render_page_png, doc.data, info.number)
            outcome = await ocr.read(png, info.number)
            info.ocr_engine, info.ocr_confidence = outcome.engine, outcome.confidence
            info.text_chars = sum(len(b.text) for b in outcome.blocks)
            loaded.blocks.extend(outcome.blocks)
            if outcome.warning:
                loaded.warnings.append(outcome.warning)
        if on_page is not None:
            await on_page(info.number, total)
    loaded.blocks.sort(key=lambda b: b.page or 0)  # stable: OCR'd pages slot into page order
    return loaded


async def _load_image(data: bytes, ocr: "OcrEngine") -> Loaded:
    loaded = Loaded(kind="image")
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if img.format != "PNG" and img.format != "JPEG":
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "PNG")
                data = buf.getvalue()
    except Exception as exc:  # not an image after all
        loaded.warnings.append(f"could not open the image: {type(exc).__name__}")
        return loaded
    outcome = await ocr.read(data, 1)
    loaded.pages.append(PageInfo(number=1, width=float(width), height=float(height), ocr=True,
                                 ocr_engine=outcome.engine, ocr_confidence=outcome.confidence,
                                 text_chars=sum(len(b.text) for b in outcome.blocks)))
    loaded.blocks = outcome.blocks
    if outcome.warning:
        loaded.warnings.append(outcome.warning)
    return loaded


__all__ = ["InputDocument", "Loaded", "RawBlock", "detect_kind", "load_document", "parse_markdown"]

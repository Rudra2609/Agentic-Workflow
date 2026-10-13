"""OCR for scanned pages and photos (spec item 2.1, plan §0).

Order: the ``vision`` model first (Gemini through the team key pool; it returns Markdown, so headings, lists and
tables survive), then local Tesseract. A local-only project, a missing key pool or a failed call raises
:class:`VisionUnavailable` and Tesseract takes over; without Tesseract the page is reported in the warnings.
Vision transcriptions are cached by image hash, so a page is never sent twice.
"""

import asyncio
import io
import re
import shutil
import statistics
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image, ImageFilter, ImageOps

from hmap.agents.doc_intel.cache import ResultCache, cache_key
from hmap.agents.doc_intel.loaders.base import (
    BULLET_RE,
    NUMBER_RE,
    RawBlock,
    clean_spaces,
    join_lines,
    rows_to_markdown,
)
from hmap.agents.doc_intel.loaders.text import parse_markdown
from hmap.core.errors import HmapError
from hmap.core.llm.base import LLMClient
from hmap.core.llm.errors import VisionUnavailable
from hmap.core.tracing import get_logger

log = get_logger("hmap.doc_intel.ocr")

VISION_PROMPT_VERSION = "1"
VISION_PROMPT = (
    "Transcribe every word on this page exactly as written, in reading order. Output Markdown only: '#' and '##' for "
    "headings, '-' or '1.' for list items, Markdown pipe tables for tables (one row per line, keep every cell, "
    "repeat a merged cell's text in each row it covers). Do not summarise, translate, correct or add anything. "
    "Skip page numbers and running headers or footers. If the page has no text, output nothing."
)
MARKS_LINE_RE = re.compile(r"^(.*?\w)[\s,.|/]+(\d{1,3}(?:\.\d+)?)$")
RULE_EDGE_RE = re.compile(r"^[|/\\\[\](){}!,;:_\s]+|[|/\\\[\](){}!,;:_\s]+$")
# how Tesseract often reads a round bullet: a degree sign, a dot or a similar mark before a capital letter
OCR_BULLET_RE = re.compile(r"^[\u00b0\u2022\u00b7.,*\u00ab\u00a2\u00a9\u00ae]\s*(?=[A-Z0-9])")


@dataclass
class OcrOutcome:
    blocks: list[RawBlock] = field(default_factory=list)
    engine: str | None = None
    confidence: float | None = None
    warning: str | None = None


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


MIN_DESKEW_DEG = 2.0
_DARK = bytes(1 if v < 140 else 0 for v in range(256))


def _erase_runs(img: Image.Image, min_run: int) -> Image.Image:
    """Whiten every horizontal run of dark pixels at least ``min_run`` long (table rules, underlines)."""
    w, h = img.size
    data = bytearray(img.tobytes())
    run = re.compile(rb"\x01{%d,}" % min_run)
    for y in range(h):
        row = bytes(data[y * w:(y + 1) * w]).translate(_DARK)
        for m in run.finditer(row):
            data[y * w + m.start():y * w + m.end()] = b"\xff" * (m.end() - m.start())
    return Image.frombytes("L", (w, h), bytes(data))


def _remove_rules(img: Image.Image) -> Image.Image:
    """Ruled table lines make Tesseract drop whole tables: erase long horizontal and vertical lines first."""
    img = _erase_runs(img, max(80, img.width // 6))
    turned = _erase_runs(img.transpose(Image.Transpose.ROTATE_90), max(60, img.height // 40))
    return turned.transpose(Image.Transpose.ROTATE_270)


def _deskew(img: Image.Image) -> Image.Image:
    """Straighten a tilted photo: the angle (within +-3 degrees) whose row profile is sharpest wins, i.e. text lines
    fall on whole pixel rows. Rows are averaged by resizing to one pixel wide (fast, no numpy). Tilts under
    ``MIN_DESKEW_DEG`` are left alone: Tesseract copes with them, and re-rotating blurs the letters (measured on the
    gold scan: word accuracy 0.98 without vs 0.96 with)."""
    small = img.resize((max(1, img.width // 4), max(1, img.height // 4)))

    def sharpness(angle: float) -> float:
        rows = list(small.rotate(angle, expand=False, fillcolor=255).resize((1, small.height), Image.Resampling.BOX)
                    .tobytes())
        mean = sum(rows) / len(rows)
        return sum((v - mean) ** 2 for v in rows)

    best = max((a / 4 for a in range(-12, 13)), key=sharpness)
    if abs(best) < MIN_DESKEW_DEG:
        return img
    return img.rotate(best, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)


def _prepare(png: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(png)).convert("L")
    if img.width < 1600:  # small photos: upscale so letters are ~30 px high
        factor = 1600 / img.width
        img = img.resize((1600, int(img.height * factor)), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.MedianFilter(3))  # speckle noise
    return _remove_rules(_deskew(ImageOps.autocontrast(img, cutoff=1)))


def _tesseract_blocks(png: bytes, page: int | None) -> tuple[list[RawBlock], float | None]:
    import pytesseract

    img = _prepare(png)
    data: dict[str, list[Any]] = pytesseract.image_to_data(img, config="--psm 4",
                                                           output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], list[int]] = {}
    for i, word in enumerate(data["text"]):
        if str(word).strip() and float(data["conf"][i]) >= 0:
            lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
    confs = [float(data["conf"][i]) / 100 for idxs in lines.values() for i in idxs]
    if not lines:
        return [], None
    w, h = img.size

    def line_info(idxs: list[int]) -> dict[str, Any]:
        x0 = min(data["left"][i] for i in idxs)
        top = min(data["top"][i] for i in idxs)
        x1 = max(data["left"][i] + data["width"][i] for i in idxs)
        bottom = max(data["top"][i] + data["height"][i] for i in idxs)
        text = OCR_BULLET_RE.sub("- ", clean_spaces(" ".join(str(data["text"][i]) for i in idxs)))
        text = RULE_EDGE_RE.sub("", text)  # remnants of table rules at either end of a line
        return {"text": text, "box": (x0, top, x1, bottom),
                "height": statistics.median(data["height"][i] for i in idxs)}

    paragraphs: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for key in sorted(lines):
        paragraphs.setdefault(key[:2], []).append(line_info(lines[key]))
    median_h = statistics.median(ln["height"] for para in paragraphs.values() for ln in para)
    blocks: list[RawBlock] = []
    for para in paragraphs.values():
        box = (min(ln["box"][0] for ln in para) / w, min(ln["box"][1] for ln in para) / h,
               max(ln["box"][2] for ln in para) / w, max(ln["box"][3] for ln in para) / h)
        bbox = (round(box[0], 4), round(box[1], 4), round(box[2], 4), round(box[3], 4))
        texts = [ln["text"] for ln in para]
        marks = [MARKS_LINE_RE.match(t) for t in texts]
        if len(texts) >= 2 and sum(1 for m in marks if m) >= max(2, int(0.6 * len(texts))):
            rows = [[m.group(1), m.group(2)] if m else [t, ""] for t, m in zip(texts, marks, strict=True)]
            blocks.append(RawBlock("table", rows_to_markdown(rows), page=page, bbox=bbox, rows=rows,
                                   ocr=True))
            continue
        start = 0
        for j in range(1, len(texts) + 1):  # split a paragraph at list markers
            if j == len(texts) or BULLET_RE.match(texts[j]) or NUMBER_RE.match(texts[j]):
                chunk = texts[start:j]
                text = join_lines(chunk)
                height = statistics.median(ln["height"] for ln in para[start:j])
                marker = BULLET_RE.match(text) or NUMBER_RE.match(text)
                if marker:
                    blocks.append(RawBlock("list_item", text[marker.end():], page=page, bbox=bbox,
                                           ocr=True))
                elif len(chunk) == 1 and len(text) < 90 and not text.endswith(".") and height >= 1.2 * median_h:
                    blocks.append(RawBlock("heading", text, page=page, bbox=bbox, size=height / median_h,
                                           ocr=True))
                else:
                    blocks.append(RawBlock("paragraph", text, page=page, bbox=bbox, ocr=True))
                start = j
    return blocks, round(statistics.mean(confs), 3) if confs else None


class OcrEngine:
    def __init__(self, llm: LLMClient | None, cache: ResultCache | None = None, *,
                 use_tesseract: bool | None = None) -> None:
        self.llm = llm
        self.cache = cache
        self.use_tesseract = tesseract_available() if use_tesseract is None else use_tesseract

    async def read(self, png: bytes, page: int | None) -> OcrOutcome:
        text = await self._vision(png)
        if text is not None:
            return OcrOutcome(parse_markdown(text, page=page, ocr=True), engine="vision")
        if self.use_tesseract:
            try:
                blocks, conf = await asyncio.to_thread(_tesseract_blocks, png, page)
                return OcrOutcome(blocks, engine="tesseract", confidence=conf)
            except Exception as exc:  # tesseract crashed or is misconfigured
                log.warning("doc_intel.ocr.tesseract_failed", error=type(exc).__name__)
                return OcrOutcome(warning=f"page {page}: Tesseract failed ({type(exc).__name__})")
        return OcrOutcome(warning=f"page {page or 1} is a scan or image, but no OCR is available (no vision model for "
                                  "this project and Tesseract is not installed: brew install tesseract)")

    async def _vision(self, png: bytes) -> str | None:
        if self.llm is None:
            return None
        key = cache_key("ocr", VISION_PROMPT_VERSION, VISION_PROMPT, png)
        if self.cache is not None and (hit := await self.cache.get(key)) is not None:
            return hit
        try:
            resp = await self.llm.read_images(VISION_PROMPT, [png], max_tokens=4096)
        except VisionUnavailable:
            return None
        except (HmapError, httpx.HTTPError) as exc:
            log.warning("doc_intel.ocr.vision_failed", error=type(exc).__name__)
            return None
        text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", resp.text.strip())
        if self.cache is not None:
            await self.cache.put(key, text)
        return text

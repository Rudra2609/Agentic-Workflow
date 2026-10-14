"""From fetched bytes to the cleaned text that evidence quotes are checked against (Sprint 5 item 5.4, plan D6).

HTML -> hidden parts removed (``sanitize``) -> ``trafilatura`` main text (no menus, footers, comments) -> invisible
characters and AI-directed lines removed. PDF -> Member 2's ``load_pdf`` (text layer only; web PDFs are not OCRed).
Plain text -> as is. The result's sha256 is the page's ``content_sha256``.
"""

import asyncio
import re

from hmap.agents.research import sanitize
from hmap.agents.research.model import Hit, Kind, Page, now, sha256_text

MIN_TEXT_CHARS = 200


class CleanError(Exception):
    """Nothing usable in the page (too short, unsupported type, unparsable)."""


def _html_to_text(raw: str) -> tuple[str, str, str | None]:
    import trafilatura

    visible = sanitize.strip_hidden_html(raw)
    # deduplicate=False: trafilatura's de-duplication remembers paragraphs across ALL pages of the process, so the
    # same page would clean to different text (and hash) depending on what was read before
    text = trafilatura.extract(visible, include_comments=False, include_tables=True, include_links=False,
                               include_images=False, favor_precision=True, deduplicate=False) or ""
    title, date = "", None
    try:
        meta = trafilatura.extract_metadata(visible)
        if meta is not None:
            title = meta.title or ""
            date = meta.date
    except Exception:
        pass
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return text, title, date


async def _pdf_to_text(data: bytes) -> str:
    from hmap.agents.doc_intel.loaders.pdf import load_pdf

    loaded = await asyncio.to_thread(load_pdf, data)            # synchronous: run it in a thread
    return "\n".join(b.text for b in loaded.blocks if b.text)


async def clean(data: bytes, *, url: str, media_type: str, hit: Hit | None = None, final_url: str | None = None,
                kind: Kind | None = None, provider: str = "") -> Page:
    mt = (media_type or "").split(";")[0].strip().lower()
    title, published = (hit.title if hit else ""), (hit.published if hit else None)
    if mt == "application/pdf" or data[:4] == b"%PDF":
        text = await _pdf_to_text(data)
        mt = "application/pdf"
    elif mt in ("text/html", "application/xhtml+xml") or \
            data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        html = data.decode("utf-8", errors="replace")
        text, html_title, date = await asyncio.to_thread(_html_to_text, html)
        title = html_title or title
        published = date or published
        mt = "text/html"
    elif mt.startswith("text/") or not mt:
        text = data.decode("utf-8", errors="replace")
        mt = mt or "text/plain"
    else:
        raise CleanError(f"unsupported type {mt}")
    return page_from_text(text, url=url, title=title, kind=kind or (hit.kind if hit else "web"),
                          provider=provider or (hit.provider if hit else ""), media_type=mt, published=published,
                          final_url=final_url)


def page_from_text(text: str, *, url: str, title: str = "", kind: Kind = "web", provider: str = "",
                   media_type: str = "text/plain", published: str | None = None, final_url: str | None = None,
                   from_cache: bool = False, license: str | None = None, min_chars: int = MIN_TEXT_CHARS) -> Page:
    cleaned, removed = sanitize.clean_text(text)
    if len(cleaned) < min_chars:
        raise CleanError(f"too little text ({len(cleaned)} characters)")
    return Page(url=url, final_url=final_url if final_url and final_url != url else None, title=title.strip()[:300],
                kind=kind, provider=provider, text=cleaned, content_sha256=sha256_text(cleaned), retrieved_at=now(),
                published=published, media_type=media_type, from_cache=from_cache, injection_lines_removed=removed,
                license=license)

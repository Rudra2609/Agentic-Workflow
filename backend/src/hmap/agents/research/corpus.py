"""The offline corpus (Sprint 5 item 5.14, plan D16): cleaned pages committed under ``samples/research/corpus/``
(permissive licences only, see ``samples/research/LICENSES.md``) plus anything fetched earlier into the local cache
(``data/research_cache/pages/``). In ``cached`` / ``local`` mode this is the whole web.

One JSON file per page (a :class:`~hmap.agents.research.model.Page`), named by the URL's sha256. Also a small BM25
search over the pages, used by the ``local`` provider so an unrecorded query still finds something offline.
"""

import json
import re
import threading
from collections.abc import Iterable
from pathlib import Path

from hmap.agents.research.model import Page, url_key
from hmap.core.config import REPO_ROOT

CORPUS_DIR = REPO_ROOT / "samples" / "research" / "corpus"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was", "be", "by", "as", "at",
    "it", "this", "that", "from", "how", "what", "why", "which", "when", "who", "does", "do", "can", "use", "using",
    "vs", "versus", "than", "into", "its", "their"
})


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class PageStore:
    """Pages by URL from several folders (the first folder that has a URL wins); ``save`` writes to ``write_dir``."""

    def __init__(self, dirs: Iterable[Path], write_dir: Path | None = None) -> None:
        self.dirs = [d for d in dirs]
        self.write_dir = write_dir
        self._pages: dict[str, Page] | None = None
        self._lock = threading.Lock()
        self._bm25: object | None = None
        self._order: list[str] = []

    def _load(self) -> dict[str, Page]:
        with self._lock:
            if self._pages is None:
                pages: dict[str, Page] = {}
                for d in reversed(self.dirs):            # earlier folders override later ones
                    if not d.is_dir():
                        continue
                    for f in sorted(d.glob("*.json")):
                        try:
                            page = Page.model_validate_json(f.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        pages[page.url] = page
                self._pages = pages
            return self._pages

    def get(self, url: str) -> Page | None:
        page = self._load().get(url.strip())
        return page.model_copy(update={"from_cache": True}) if page else None

    def pages(self) -> list[Page]:
        return list(self._load().values())

    def save(self, page: Page) -> None:
        if self.write_dir is None:
            return
        self.write_dir.mkdir(parents=True, exist_ok=True)
        path = self.write_dir / f"{url_key(page.url)[:32]}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(page.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(path)
        with self._lock:
            if self._pages is not None:
                self._pages[page.url] = page
            self._bm25 = None

    def search(self, query: str, k: int = 5) -> list[tuple[Page, float]]:
        """BM25 over title + text of every page (title words count three times)."""
        from rank_bm25 import BM25Plus

        pages = self._load()
        with self._lock:
            if self._bm25 is None or len(self._order) != len(pages):
                self._order = sorted(pages)
                docs = [tokens(pages[u].title) * 3 + tokens(pages[u].text) for u in self._order]
                self._bm25 = BM25Plus(docs) if docs else None
            bm25, order = self._bm25, list(self._order)
        q = tokens(query)
        if bm25 is None or not q:
            return []
        scores = bm25.get_scores(q)  # type: ignore[union-attr]
        ranked = sorted(range(len(order)), key=lambda i: (-scores[i], order[i]))[:k]
        return [(pages[order[i]], float(scores[i])) for i in ranked if scores[i] > 0]


def corpus_meta() -> dict[str, object]:
    """Summary of the committed corpus (for the API / docs)."""
    files = sorted(CORPUS_DIR.glob("*.json")) if CORPUS_DIR.is_dir() else []
    kinds: dict[str, int] = {}
    for f in files:
        try:
            kind = str(json.loads(f.read_text(encoding="utf-8")).get("kind", "web"))
        except Exception:
            continue
        kinds[kind] = kinds.get(kind, 0) + 1
    return {"pages": len(files), "by_kind": kinds}

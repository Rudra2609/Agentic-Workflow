"""Public search-provider registry (Sprint 5 item 5.2; reused by Member 6, Sprint 6 item 6.4).

    from hmap.agents.research.providers import get_providers
    for provider in get_providers(["wikipedia", "local"], mode="cached"):
        hits = await provider.search("TCP message framing", k=5)
"""

from collections.abc import Sequence

import httpx

from hmap.agents.research.corpus import CORPUS_DIR, PageStore
from hmap.agents.research.model import Hit, Page
from hmap.agents.research.providers.base import (
    SAMPLE_SEARCH_CACHE,
    CachedProvider,
    SearchCache,
    SearchError,
    SearchProvider,
)
from hmap.agents.research.providers.local import LocalProvider
from hmap.agents.research.providers.web import (
    ArxivProvider,
    DuckDuckGoProvider,
    WikipediaProvider,
    http_client,
)
from hmap.core.config import Settings

KNOWN = ("wikipedia", "arxiv", "ddg", "local")


def page_store(settings: Settings | None = None) -> PageStore:
    s = settings or Settings.from_env()
    return PageStore([CORPUS_DIR, s.research_cache_dir / "pages"], write_dir=s.research_cache_dir / "pages")


def get_providers(names: Sequence[str] | None = None, *, mode: str | None = None, settings: Settings | None = None,
                  store: PageStore | None = None, project_pages: list[Page] | None = None,
                  client: httpx.AsyncClient | None = None) -> list[CachedProvider]:
    """Providers in the given order, each behind the search cache and obeying ``mode`` (``local`` keeps only the
    local provider). Unknown names are ignored. ``client`` lets tests inject a mock transport."""
    s = settings or Settings.from_env()
    mode = mode or s.research_mode
    wanted = [n for n in (names or s.research_providers) if n in KNOWN]
    if mode == "local":
        wanted = ["local"]
    store = store or page_store(s)
    cache = SearchCache([SAMPLE_SEARCH_CACHE, s.research_cache_dir / "search"], s.research_cache_dir / "search")
    http = client or http_client()
    out: list[CachedProvider] = []
    for name in wanted:
        inner: SearchProvider
        if name == "wikipedia":
            inner = WikipediaProvider(http)
        elif name == "arxiv":
            inner = ArxivProvider(http)
        elif name == "ddg":
            inner = DuckDuckGoProvider()
        else:
            inner = LocalProvider(store, project_pages)
        out.append(CachedProvider(inner, cache, mode))
    return out


__all__ = ["KNOWN", "ArxivProvider", "CachedProvider", "DuckDuckGoProvider", "Hit", "LocalProvider", "SearchCache",
           "SearchError", "SearchProvider", "WikipediaProvider", "get_providers", "page_store"]

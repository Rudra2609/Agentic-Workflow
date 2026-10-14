"""Live search providers (Sprint 5 item 5.2): Wikipedia and arXiv over their public APIs (``httpx``), DuckDuckGo via
``ddgs``. Each returns plain :class:`Hit` objects; failures raise :class:`SearchError` (the agent moves on)."""

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from hmap.agents.research.model import Hit, Kind
from hmap.agents.research.providers.base import SearchError

USER_AGENT = "hmap-research/1.0 (IT314 student project; runs on one laptop; polite, cached)"


def http_client(transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, timeout=timeout, headers={"User-Agent": USER_AGENT},
                             follow_redirects=False)


class WikipediaProvider:
    """English Wikipedia search; the article's plain text comes inline (TextExtracts API), so nothing is scraped."""

    name = "wikipedia"
    kind: Kind = "wiki"
    network = True
    api = "https://en.wikipedia.org/w/api.php"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        try:
            r = await self.client.get(self.api, params={"action": "query", "list": "search", "srsearch": query,
                                                        "srlimit": k, "format": "json", "utf8": 1})
            r.raise_for_status()
            results = r.json().get("query", {}).get("search", [])
        except Exception as exc:
            raise SearchError(f"wikipedia: {type(exc).__name__}") from exc
        hits: list[Hit] = []
        for n, item in enumerate(results[:k]):
            title = str(item.get("title", ""))
            if not title:
                continue
            text = await self._extract(title)
            if not text:
                continue
            hits.append(Hit(provider=self.name, kind="wiki", rank=n, query=query, title=title,
                            url=f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                            snippet=_strip_tags(str(item.get("snippet", ""))), content=text))
        return hits

    async def _extract(self, title: str) -> str:
        try:
            r = await self.client.get(self.api, params={"action": "query", "prop": "extracts", "explaintext": 1,
                                                        "titles": title, "format": "json", "redirects": 1})
            r.raise_for_status()
            pages: dict[str, Any] = r.json().get("query", {}).get("pages", {})
        except Exception:
            return ""
        return next((str(p.get("extract") or "") for p in pages.values()), "")


class ArxivProvider:
    """arXiv search (Atom API). The abstract (CC0 metadata) is the page text; PDFs are not downloaded."""

    name = "arxiv"
    kind: Kind = "arxiv"
    network = True
    api = "https://export.arxiv.org/api/query"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        from lxml import etree

        terms = [t for t in query.replace('"', " ").split() if len(t) > 2][:8]
        if not terms:
            return []
        search = " AND ".join(f"all:{t}" for t in terms)
        try:
            r = await self.client.get(self.api, params={"search_query": search, "max_results": k,
                                                        "sortBy": "relevance"})
            r.raise_for_status()
            root = etree.fromstring(r.content)
        except Exception as exc:
            raise SearchError(f"arxiv: {type(exc).__name__}") from exc
        ns = {"a": "http://www.w3.org/2005/Atom"}
        hits: list[Hit] = []
        for n, entry in enumerate(root.findall("a:entry", ns)[:k]):
            url = (entry.findtext("a:id", default="", namespaces=ns) or "").strip().replace("http://", "https://")
            title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
            summary = " ".join((entry.findtext("a:summary", default="", namespaces=ns) or "").split())
            published = (entry.findtext("a:published", default="", namespaces=ns) or "")[:10] or None
            if url and summary:
                hits.append(Hit(provider=self.name, kind="arxiv", rank=n, query=query, url=url, title=title,
                                snippet=summary[:300], published=published, content=f"{title}\n\n{summary}"))
        return hits


class DuckDuckGoProvider:
    """DuckDuckGo web search via ``ddgs`` (no API key). Often rate-limited: the cache and the other providers cover
    for it."""

    name = "ddg"
    kind: Kind = "web"
    network = True

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        def run() -> list[dict[str, Any]]:
            from ddgs import DDGS

            return list(DDGS(timeout=10).text(query, max_results=k, safesearch="moderate") or [])

        try:
            results = await asyncio.to_thread(run)
        except Exception as exc:
            raise SearchError(f"ddg: {type(exc).__name__}") from exc
        return [Hit(provider=self.name, kind="web", rank=n, query=query, url=str(r.get("href", "")),
                    title=str(r.get("title", "")), snippet=str(r.get("body", ""))[:300])
                for n, r in enumerate(results[:k]) if str(r.get("href", "")).startswith(("http://", "https://"))]


def _strip_tags(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text)

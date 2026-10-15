"""Search providers (Sprint 5 item 5.2, plan D4): one small protocol, a cache in front of every provider, and a
public registry (Member 6 reuses the providers for independent verification queries, Sprint 6 item 6.4).

    providers = get_providers(["wikipedia", "arxiv", "ddg", "local"], mode="cached")
    hits = await providers[0].search("asyncio vs threads for TCP servers", k=5)

Modes (``HMAP_RESEARCH_MODE``): ``online`` = cached answer if there is one, else the live search (then cached);
``cached`` = cached answers only, never the network (an unrecorded query returns nothing); ``local`` = only the
``local`` provider. Cached search results live in ``samples/research/search_cache/`` (committed, read-only) and
``data/research_cache/search/`` (written by online runs).
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from hmap.agents.research.model import Hit, Kind, sha256_text
from hmap.core.config import REPO_ROOT
from hmap.core.tracing import get_logger

log = get_logger("hmap.research.providers")

SAMPLE_SEARCH_CACHE = REPO_ROOT / "samples" / "research" / "search_cache"


class SearchError(Exception):
    """A provider failed (network, rate limit, bad answer). The caller moves on to the next provider."""


@runtime_checkable
class SearchProvider(Protocol):
    name: str
    kind: Kind
    network: bool                       # False = works offline (the local corpus)

    async def search(self, query: str, k: int = 5) -> list[Hit]: ...


def normalise_query(query: str) -> str:
    return " ".join(query.lower().split())


class SearchCache:
    """Search results by (provider, normalised query). Reads every folder, writes the last one."""

    def __init__(self, read_dirs: Sequence[Path], write_dir: Path | None) -> None:
        self.read_dirs = list(read_dirs)
        self.write_dir = write_dir

    @staticmethod
    def _name(provider: str, query: str) -> str:
        return f"{provider}/{sha256_text(provider + '|' + normalise_query(query))[:32]}.json"

    def get(self, provider: str, query: str) -> list[Hit] | None:
        name = self._name(provider, query)
        for d in self.read_dirs:
            path = d / name
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return [Hit.model_validate(h) for h in data.get("hits", [])]
                except Exception:
                    continue
        return None

    def put(self, provider: str, query: str, hits: list[Hit]) -> None:
        if self.write_dir is None:
            return
        path = self.write_dir / self._name(provider, query)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"provider": provider, "query": normalise_query(query), "saved_at": datetime.now(UTC).isoformat(),
                "hits": [h.model_dump(mode="json", exclude={"content"}) | ({"content": h.content} if h.content
                                                                            else {}) for h in hits]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


class CachedProvider:
    """A provider behind the search cache, obeying the research mode."""

    def __init__(self, inner: SearchProvider, cache: SearchCache, mode: str) -> None:
        self.inner = inner
        self.cache = cache
        self.mode = mode
        self.name = inner.name
        self.kind = inner.kind
        self.network = inner.network
        self.live_calls = 0

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        if not self.inner.network:                       # the local corpus: always live, never cached
            return await self.inner.search(query, k)
        cached = self.cache.get(self.name, query)
        if cached is not None:
            return [h.model_copy(update={"query": query}) for h in cached[:k]]
        if self.mode != "online":
            return []
        self.live_calls += 1
        hits = await self.inner.search(query, k)
        self.cache.put(self.name, query, hits)
        return hits

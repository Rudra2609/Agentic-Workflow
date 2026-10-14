"""Shared helpers for Member 5's tests: a tiny page corpus, a page store in a temp folder, a fake provider."""

from pathlib import Path
from typing import Any

import pytest

from hmap.agents.research.clean import page_from_text
from hmap.agents.research.corpus import PageStore
from hmap.agents.research.model import Hit, Kind, Page

ASYNCIO_URL = "https://docs.python.org/3/library/asyncio.html"
THREAD_URL = "https://en.wikipedia.org/wiki/Thread_(computing)"
SELECTORS_URL = "https://docs.python.org/3/library/selectors.html"
BLOG_URL = "https://example-blog.com/threads-vs-asyncio"

TEXTS: dict[str, tuple[str, Kind, str]] = {
    ASYNCIO_URL: ("asyncio — Asynchronous I/O", "web",
                  "asyncio is a library to write concurrent code using the async/await syntax. asyncio is used as a "
                  "foundation for multiple Python asynchronous frameworks that provide high-performance network and "
                  "web-servers. An event loop runs in a single thread and multiplexes many sockets. Coroutines yield "
                  "control while they wait for I/O, so one thread can serve thousands of connections."),
    THREAD_URL: ("Thread (computing)", "wiki",
                 "In computer science, a thread of execution is the smallest sequence of programmed instructions that "
                 "can be managed independently by a scheduler. In CPython the global interpreter lock lets only one "
                 "thread execute Python bytecode at a time. A thread-per-client server is simple to write, but each "
                 "thread costs memory and context switches between many threads add overhead."),
    SELECTORS_URL: ("selectors — High-level I/O multiplexing", "web",
                    "This module allows high-level and efficient I/O multiplexing, built upon the select module "
                    "primitives. Users are encouraged to use this module instead, unless they want precise control "
                    "over the OS-level primitives used. The DefaultSelector picks the most efficient implementation "
                    "available on the platform, such as epoll or kqueue."),
}


def make_page(url: str, title: str, text: str, kind: Kind = "web", provider: str = "seed") -> Page:
    return page_from_text(text, url=url, title=title, kind=kind, provider=provider)


@pytest.fixture
def store(tmp_path: Path) -> PageStore:
    s = PageStore([tmp_path / "corpus"], write_dir=tmp_path / "corpus")
    for url, (title, kind, text) in TEXTS.items():
        s.save(make_page(url, title, text, kind))
    return s


class FakeProvider:
    """Returns fixed hits per query substring; counts calls."""

    network = True

    def __init__(self, name: str = "fake", kind: Kind = "web", hits: dict[str, list[str]] | None = None,
                 content: dict[str, str] | None = None) -> None:
        self.name, self.kind = name, kind
        self.hits = hits or {}
        self.content = content or {}
        self.calls: list[str] = []

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        self.calls.append(query)
        urls = next((v for key, v in self.hits.items() if key in query.lower()), [])
        return [Hit(provider=self.name, kind=self.kind, url=u, title=u.rsplit("/", 1)[-1], rank=n, query=query,
                    content=self.content.get(u)) for n, u in enumerate(urls[:k])]


def cached(provider: Any, tmp_path: Path, mode: str = "online") -> Any:
    from hmap.agents.research.providers.base import CachedProvider, SearchCache

    return CachedProvider(provider, SearchCache([tmp_path / "search"], tmp_path / "search"), mode)

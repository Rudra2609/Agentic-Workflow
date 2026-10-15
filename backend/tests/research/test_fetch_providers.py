"""Fetcher (5.3: safety, robots, rate limit, retries, size / type limits, cache) and providers (5.2)."""

import json
import time
from pathlib import Path

import httpx
import pytest

from hmap.agents.research.corpus import PageStore
from hmap.agents.research.fetch import Blocked, Fetcher, check_url
from hmap.agents.research.model import Hit
from hmap.agents.research.providers import get_providers
from hmap.agents.research.providers.local import LocalProvider
from hmap.agents.research.providers.web import ArxivProvider, WikipediaProvider
from hmap.core.config import Settings
from tests.research.conftest import ASYNCIO_URL, FakeProvider, cached, make_page

HTML = ("<html><head><title>Sockets HOWTO</title></head><body><nav>menu menu</nav><article><h1>Sockets</h1>"
        "<p>A socket is one endpoint of a two-way communication link between two programs on the network.</p>"
        "<p>Servers call listen and accept to wait for clients; clients call connect to reach a server.</p>"
        "<p>Non-blocking sockets return immediately instead of waiting, so one thread can watch many of them.</p>"
        "<p>The selectors module tells a program which sockets are ready to read or write at any moment.</p>"
        "</article></body></html>")


async def public(host: str) -> list[str]:
    return ["93.184.216.34"]


def transport(routes: dict[str, httpx.Response], calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/projects", "http://localhost/admin", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "file:///etc/passwd",
    "ftp://example.com/x", "http://example.com:5432/", "http://user:pw@example.com/", "http://printer.local/",
])
async def test_ssrf_guard_refuses_local_and_odd_urls(url: str) -> None:
    with pytest.raises(Blocked):
        await check_url(url, public)


async def test_a_public_name_that_resolves_to_a_private_address_is_refused() -> None:
    async def evil(host: str) -> list[str]:
        return ["127.0.0.1"]

    with pytest.raises(Blocked):
        await check_url("https://innocent-looking.example/", evil)
    await check_url("https://example.org/page", public)               # a public address passes


async def test_redirect_to_a_private_address_is_refused(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"https://site.example/robots.txt": httpx.Response(404),
              "https://site.example/a": httpx.Response(302, headers={"location": "http://127.0.0.1:8000/api"})}
    f = Fetcher(store=PageStore([], tmp_path / "p"), mode="online", resolver=public, rate_per_host=1000,
                client=httpx.AsyncClient(transport=transport(routes, calls)))
    result = await f.fetch(Hit(provider="ddg", url="https://site.example/a"))
    assert result.page is None and result.reason == "blocked"
    assert not any("127.0.0.1" in c for c in calls)


async def test_fetch_cleans_caches_and_a_rerun_makes_no_network_call(tmp_path: Path) -> None:
    calls: list[str] = []
    routes = {"https://docs.example/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /private\n"),
              "https://docs.example/sockets": httpx.Response(200, text=HTML,
                                                             headers={"content-type": "text/html; charset=utf-8"})}
    client = httpx.AsyncClient(transport=transport(routes, calls))
    store = PageStore([tmp_path / "p"], tmp_path / "p")
    f = Fetcher(store=store, mode="online", resolver=public, rate_per_host=1000, client=client)
    result = await f.fetch(Hit(provider="ddg", url="https://docs.example/sockets"))
    assert result.reason == "ok" and result.page is not None
    assert "one endpoint of a two-way communication link" in result.page.text and "menu menu" not in result.page.text
    assert result.page.title in ("Sockets", "Sockets HOWTO")
    assert (await f.fetch(Hit(provider="ddg", url="https://docs.example/private/x"))).reason == "robots"
    n = len(calls)
    again = Fetcher(store=PageStore([tmp_path / "p"]), mode="cached", resolver=public)   # fresh process, no network
    second = await again.fetch(Hit(provider="ddg", url="https://docs.example/sockets"))
    assert second.reason == "cached" and second.page is not None and second.page.from_cache
    assert again.network_calls == 0 and len(calls) == n
    assert (await again.fetch(Hit(provider="ddg", url="https://docs.example/other"))).reason == "not_in_cache"


async def test_size_type_retries_and_rate_limit(tmp_path: Path) -> None:
    calls: list[str] = []
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/big":
            return httpx.Response(200, content=b"x" * 3000, headers={"content-type": "text/plain"})
        if request.url.path == "/image":
            return httpx.Response(200, content=b"\x89PNG....", headers={"content-type": "image/png"})
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, text="plain text " * 40, headers={"content-type": "text/plain"})

    f = Fetcher(store=PageStore([], tmp_path / "p"), mode="online", resolver=public, rate_per_host=20,
                max_bytes=1000, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await f.fetch(Hit(provider="x", url="https://h.example/big"))).reason == "size"
    assert (await f.fetch(Hit(provider="x", url="https://h.example/image"))).reason == "type"
    started = time.monotonic()
    ok = await f.fetch(Hit(provider="x", url="https://h.example/flaky"))
    assert ok.reason == "ok" and attempts["n"] == 3                   # two 503s retried
    assert time.monotonic() - started >= 2 / 20 * 0.9                 # requests to one host are spaced


async def test_inline_content_needs_no_fetch(tmp_path: Path) -> None:
    f = Fetcher(store=PageStore([], tmp_path / "p"), mode="cached")
    text = "An abstract about concurrency in network servers and the costs of threads. " * 3
    r = await f.fetch(Hit(provider="arxiv", kind="arxiv", url="https://arxiv.org/abs/1", title="T", content=text))
    assert r.reason == "inline" and r.page is not None and r.page.kind == "arxiv" and f.network_calls == 0


async def test_search_cache_obeys_the_mode(tmp_path: Path) -> None:
    fake = FakeProvider(hits={"asyncio": [ASYNCIO_URL]})
    online = cached(fake, tmp_path, "online")
    assert [h.url for h in await online.search("asyncio servers", 3)] == [ASYNCIO_URL]
    assert [h.url for h in await online.search("ASYNCIO   servers", 3)] == [ASYNCIO_URL]   # normalised: cached
    assert fake.calls == ["asyncio servers"]
    offline = cached(fake, tmp_path, "cached")
    assert [h.url for h in await offline.search("asyncio servers", 3)] == [ASYNCIO_URL]
    assert await offline.search("never asked before", 3) == [] and len(fake.calls) == 1


async def test_local_provider_and_registry(store: PageStore, tmp_path: Path) -> None:
    project = make_page("project://doc1", "assignment.pdf", "Build a TCP chat server in Python that serves many "
                        "clients at once with the standard library only. " * 4, "local")
    local = LocalProvider(store, [project])
    hits = await local.search("python tcp chat server many clients", 5)
    assert hits and {h.url for h in hits} >= {"project://doc1"}
    settings = Settings.from_env().model_copy(update={"research_cache_dir": tmp_path / "cache"})
    names = [p.name for p in get_providers(["wikipedia", "nope", "local"], mode="cached", settings=settings,
                                           store=store)]
    assert names == ["wikipedia", "local"]
    assert [p.name for p in get_providers(mode="local", settings=settings, store=store)] == ["local"]


async def test_wikipedia_and_arxiv_parse_their_apis() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        if request.url.host == "en.wikipedia.org" and q.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"title": "Event loop",
                                                                   "snippet": "an <b>event</b> loop"}]}})
        if request.url.host == "en.wikipedia.org":
            return httpx.Response(200, json={"query": {"pages": {"1": {"extract": "In computer science, the event "
                                                                                  "loop is a design pattern."}}}})
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2101.00001v1</id>'
                '<title>Async  servers</title><summary>We compare threads and event loops for servers.</summary>'
                '<published>2021-01-01T00:00:00Z</published></entry></feed>')
        return httpx.Response(200, content=atom.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    [w] = await WikipediaProvider(client).search("event loop", 3)
    assert w.url == "https://en.wikipedia.org/wiki/Event_loop" and w.snippet == "an event loop" and w.content
    [a] = await ArxivProvider(client).search("threads event loops servers", 3)
    assert a.url == "https://arxiv.org/abs/2101.00001v1" and a.title == "Async servers" and a.published == "2021-01-01"
    assert json.loads(json.dumps(a.model_dump()))["kind"] == "arxiv"

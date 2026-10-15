"""Fetcher (Sprint 5 item 5.3, plan D5): from a search hit to a cleaned :class:`Page`, politely and safely.

Order: inline content (arXiv abstract, Wikipedia extract) -> the page store (offline corpus + local cache) -> the
network, only in ``online`` mode. On the network:

- **SSRF guard**: http(s) only, default ports only; the host's addresses are resolved and loopback / private /
  link-local / multicast / reserved ones are refused — before the request and again for every redirect (the
  platform's API, RabbitMQ and Postgres listen on 127.0.0.1; a page must never make us call them);
- robots.txt (``protego``) per host, cached; a polite User-Agent; at most ``rate_per_host`` requests/s per host;
- 10 s timeout, 2 retries with backoff on network errors and 429 / 5xx; at most ``max_bytes`` (streamed, cut off);
- HTML, PDF and plain text only.

Every fetched page goes to the store (``data/research_cache/pages``), so a re-run makes no network call at all.
:class:`FetchResult` says why a page was not fetched (shown per round in the Research tab).
"""

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from hmap.agents.research.clean import CleanError, clean, page_from_text
from hmap.agents.research.corpus import PageStore
from hmap.agents.research.model import Hit, Page
from hmap.agents.research.providers.web import USER_AGENT, http_client
from hmap.core.tracing import get_logger
from hmap.obs import span

log = get_logger("hmap.research.fetch")

ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "application/pdf", "text/plain", "text/markdown")
MAX_REDIRECTS = 5
Resolver = Callable[[str], Awaitable[list[str]]]


class Blocked(Exception):
    """The URL is not allowed (scheme, port, address, robots.txt)."""


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(i[4][0]) for i in infos})


def _bad_address(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or not ip.is_global)


async def check_url(url: str, resolver: Resolver = system_resolver) -> None:
    """Raise :class:`Blocked` unless ``url`` is a public http(s) URL on a default port."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise Blocked(f"scheme {parts.scheme or '?'} not allowed")
    if parts.username or parts.password:
        raise Blocked("credentials in URL")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test")):
        raise Blocked("local host name")
    if parts.port not in (None, 80, 443):
        raise Blocked(f"port {parts.port} not allowed")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    addresses = [str(literal)] if literal is not None else await resolver(host)
    if not addresses or any(_bad_address(a) for a in addresses):
        raise Blocked("address is not public")


@dataclass
class FetchResult:
    page: Page | None
    reason: str = "ok"            # ok | cached | inline | not_in_cache | blocked | robots | type | size | http | clean


@dataclass
class Fetcher:
    store: PageStore
    mode: str = "cached"
    client: httpx.AsyncClient | None = None
    resolver: Resolver = system_resolver
    rate_per_host: float = 1.0
    max_bytes: int = 5 * 1024 * 1024
    retries: int = 2
    extra_pages: dict[str, Page] = field(default_factory=dict)   # the project's own documents (project:// urls)
    network_calls: int = 0
    _robots: dict[str, object] = field(default_factory=dict)
    _last: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = http_client()
        return self.client

    async def fetch(self, hit: Hit) -> FetchResult:
        if hit.url in self.extra_pages:
            return FetchResult(self.extra_pages[hit.url], "cached")
        stored = self.store.get(hit.url)
        if stored is not None:
            return FetchResult(stored, "cached")
        if hit.content:
            try:
                page = page_from_text(hit.content, url=hit.url, title=hit.title, kind=hit.kind, provider=hit.provider,
                                      published=hit.published, min_chars=120)
            except CleanError:
                return FetchResult(None, "clean")
            self.store.save(page)
            return FetchResult(page, "inline")
        if self.mode != "online":
            return FetchResult(None, "not_in_cache")
        with span("research.fetch", kind="client", attrs={"server.address": urlsplit(hit.url).hostname or ""}) as sp:
            result = await self._fetch_live(hit)
            sp.set("hmap.outcome", result.reason)
        if result.page is not None:
            self.store.save(result.page)
        return result

    async def _fetch_live(self, hit: Hit) -> FetchResult:
        url = hit.url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                await check_url(url, self.resolver)
                if not await self._allowed_by_robots(url):
                    return FetchResult(None, "robots")
                response = await self._get(url)
                if response is None:
                    return FetchResult(None, "http")
                status, headers, body = response
                if status in (301, 302, 303, 307, 308) and headers.get("location"):
                    url = urljoin(url, headers["location"])
                    continue
                if status != 200:
                    return FetchResult(None, "http")
                media_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
                if media_type and media_type not in ALLOWED_TYPES:
                    return FetchResult(None, "type")
                if body is None:
                    return FetchResult(None, "size")
                try:
                    page = await clean(body, url=hit.url, media_type=media_type, hit=hit, final_url=url,
                                       provider=hit.provider)
                except CleanError:
                    return FetchResult(None, "clean")
                return FetchResult(page, "ok")
            return FetchResult(None, "http")
        except Blocked as exc:
            log.info("research fetch blocked", host=urlsplit(url).hostname, reason=str(exc))
            return FetchResult(None, "blocked")

    async def _wait_turn(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            gap = 1.0 / self.rate_per_host
            wait = self._last.get(host, 0.0) + gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def _get(self, url: str) -> tuple[int, dict[str, str], bytes | None] | None:
        host = urlsplit(url).hostname or ""
        for attempt in range(self.retries + 1):
            await self._wait_turn(host)
            try:
                self.network_calls += 1
                async with self._http().stream("GET", url, headers={"User-Agent": USER_AGENT}) as r:
                    headers = {k.lower(): v for k, v in r.headers.items()}
                    if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                        await asyncio.sleep(0.5 * 2 ** attempt)
                        continue
                    if r.status_code != 200:
                        return r.status_code, headers, b""
                    size = int(headers.get("content-length") or 0)
                    if size > self.max_bytes:
                        return 200, headers, None
                    chunks: list[bytes] = []
                    total = 0
                    async for part in r.aiter_bytes():
                        total += len(part)
                        if total > self.max_bytes:
                            return 200, headers, None
                        chunks.append(part)
                    return 200, headers, b"".join(chunks)
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt >= self.retries:
                    return None
                await asyncio.sleep(0.5 * 2 ** attempt)
        return None

    async def _allowed_by_robots(self, url: str) -> bool:
        from protego import Protego

        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rules: object = None
            try:
                await self._wait_turn(parts.hostname or "")
                self.network_calls += 1
                r = await self._http().get(origin + "/robots.txt")
                if r.status_code == 200:
                    rules = Protego.parse(r.text)
                elif r.status_code in (401, 403):
                    rules = Protego.parse("User-agent: *\nDisallow: /")
            except (httpx.TransportError, httpx.TimeoutException):
                rules = None                     # unreachable robots.txt: allowed (RFC 9309 §2.3.1.4 = 4xx/5xx rules)
            self._robots[origin] = rules
        rules = self._robots[origin]
        return rules is None or bool(rules.can_fetch(url, USER_AGENT))  # type: ignore[attr-defined]

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()

"""``bus`` fixture parametrised over adapters. Every adapter-agnostic test in this folder runs unchanged on each one.

- ``memory``: ``InMemoryBus``.
- ``rabbitmq``: ``RabbitBus`` against the dev compose stack (``make infra-up``), marked ``integration`` and skipped
  with a clear message when the broker is not reachable. Each test gets a random ``namespace`` so runs never share
  queues, and everything declared under it is deleted on teardown.
"""

import contextlib
import functools
import os
import socket
import uuid
from collections.abc import AsyncIterator, Iterable
from urllib.parse import quote, urlparse

import httpx
import pytest

from hmap.core.bus.base import COMMANDS_EXCHANGE, EVENTS_EXCHANGE, RETRY_EXCHANGE, Bus
from hmap.core.bus.memory import InMemoryBus
from hmap.core.bus.rabbitmq import DLX_EXCHANGE, RabbitBus
from tests.core.bus._helpers import MAX_ATTEMPTS, RETRY_DELAYS_S

RABBITMQ_URL = os.environ.get("HMAP_TEST_RABBITMQ_URL") or os.environ.get("HMAP_RABBITMQ_URL") \
    or "amqp://hmap:hmap@127.0.0.1:5672/"
RABBITMQ_MGMT_URL = os.environ.get("HMAP_TEST_RABBITMQ_MGMT_URL", "http://127.0.0.1:15672")

ADAPTERS = ["memory", pytest.param("rabbitmq", marks=pytest.mark.integration)]


@functools.lru_cache(maxsize=1)
def rabbitmq_unreachable_reason() -> str | None:
    """None if a TCP connection to the broker succeeds (fast check, cached for the session)."""
    parsed = urlparse(RABBITMQ_URL)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 5672
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return None
    except OSError as exc:
        return f"RabbitMQ not reachable at {host}:{port} ({exc}); start the dev stack with `make infra-up`"


def require_rabbitmq() -> None:
    reason = rabbitmq_unreachable_reason()
    if reason is not None:
        pytest.skip(reason)


def new_namespace() -> str:
    return f"t{uuid.uuid4().hex[:10]}."


def make_rabbit_bus(namespace: str, **kwargs: object) -> RabbitBus:
    return RabbitBus(RABBITMQ_URL, max_attempts=MAX_ATTEMPTS, retry_delays_s=RETRY_DELAYS_S, namespace=namespace,
                     connection_name=f"hmap-test-{namespace.rstrip('.')}", **kwargs)  # type: ignore[arg-type]


def _mgmt_auth() -> tuple[str, str]:
    parsed = urlparse(RABBITMQ_URL)
    return parsed.username or "guest", parsed.password or "guest"


def _vhost() -> str:
    path = urlparse(RABBITMQ_URL).path.lstrip("/")
    return quote(path or "/", safe="")


def known_names(bus: RabbitBus) -> tuple[set[str], set[str]]:
    """(queues, exchanges) a ``RabbitBus`` declared under its namespace (the management listing can lag)."""
    ns = bus.namespace
    queues = set(bus._queues.values()) | set(bus._declared) | set(bus._retry_queues)
    exchanges = {f"{ns}{x}" for x in (COMMANDS_EXCHANGE, EVENTS_EXCHANGE, RETRY_EXCHANGE, DLX_EXCHANGE)}
    return queues, exchanges


async def delete_namespace(namespace: str, queues: Iterable[str] = (), exchanges: Iterable[str] = ()) -> None:
    """Delete every queue and exchange whose name starts with ``namespace`` (management HTTP API): the given
    names plus whatever the management listing shows under the prefix. Missing names are ignored."""
    assert namespace, "refusing to delete without a namespace"
    vhost = _vhost()
    async with httpx.AsyncClient(base_url=RABBITMQ_MGMT_URL, auth=_mgmt_auth(), timeout=10) as client:
        for kind, known in (("queues", set(queues)), ("exchanges", set(exchanges))):
            resp = await client.get(f"/api/{kind}/{vhost}", params={"columns": "name"})
            resp.raise_for_status()
            names = {item["name"] for item in resp.json()} | known
            for name in sorted(n for n in names if n.startswith(namespace)):
                with contextlib.suppress(httpx.HTTPError):
                    await client.delete(f"/api/{kind}/{vhost}/{quote(name, safe='')}")


async def namespace_leftovers(namespace: str) -> list[str]:
    vhost = _vhost()
    names: list[str] = []
    async with httpx.AsyncClient(base_url=RABBITMQ_MGMT_URL, auth=_mgmt_auth(), timeout=10) as client:
        for kind in ("queues", "exchanges"):
            resp = await client.get(f"/api/{kind}/{vhost}", params={"columns": "name"})
            resp.raise_for_status()
            names += [i["name"] for i in resp.json() if i["name"].startswith(namespace)]
    return names


def _make_bus(name: str, namespace: str) -> Bus:
    if name == "memory":
        return InMemoryBus(max_attempts=MAX_ATTEMPTS, retry_delays_s=RETRY_DELAYS_S)
    if name == "rabbitmq":
        return make_rabbit_bus(namespace)
    raise ValueError(f"unknown bus adapter {name!r}")


@pytest.fixture(params=ADAPTERS)
async def bus(request: pytest.FixtureRequest) -> AsyncIterator[Bus]:
    if request.param == "rabbitmq":
        require_rabbitmq()
    namespace = new_namespace()
    b = _make_bus(request.param, namespace)
    try:
        await b.start()
        yield b
    finally:
        try:
            await b.close()
        finally:
            if isinstance(b, RabbitBus):
                await delete_namespace(namespace, *known_names(b))

"""Checks specific to ``RabbitBus`` against the dev broker (``make infra-up``): publisher confirms + persistence,
broker-held attempt state, non-destructive DLQ inspection, consumer reconnect, durable subscribers across bus
instances, and a real broker restart (``docker restart``) with no message loss.

Every test uses its own random namespace and deletes what it declared."""

import asyncio
import json
import shutil
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import aio_pika
import httpx
import pytest

from hmap.core.bus.base import DLQ_NAME, RETRY_EXCHANGE, Delivery, capability_queue
from hmap.core.bus.inbox import InMemoryInboxStore, idempotent
from hmap.core.bus.memory import BusClosedError
from hmap.core.bus.rabbitmq import RabbitBus
from tests.core.bus._helpers import CAP, command, event, settle, tag_of, wait_until
from tests.core.bus.conftest import (
    RABBITMQ_MGMT_URL,
    RABBITMQ_URL,
    _mgmt_auth,
    delete_namespace,
    known_names,
    make_rabbit_bus,
    namespace_leftovers,
    new_namespace,
    require_rabbitmq,
)

pytestmark = pytest.mark.integration

RABBIT_CONTAINER = "hmap-rabbitmq-1"
Q = capability_queue(CAP)

BusFactory = Callable[..., Awaitable[RabbitBus]]


@pytest.fixture
async def rabbit() -> AsyncIterator[tuple[str, BusFactory]]:
    """(namespace, factory): every bus made by the factory shares the namespace; all are closed and the namespace
    is deleted on teardown."""
    require_rabbitmq()
    namespace = new_namespace()
    buses: list[RabbitBus] = []

    async def factory(**kwargs: Any) -> RabbitBus:
        b = make_rabbit_bus(namespace, **kwargs)
        buses.append(b)
        await b.start()
        return b

    try:
        yield namespace, factory
    finally:
        queues: set[str] = set()
        exchanges: set[str] = set()
        for b in buses:
            await b.close()
            q, x = known_names(b)
            queues |= q
            exchanges |= x
        await delete_namespace(namespace, queues, exchanges)


async def _raw_get(queue: str) -> aio_pika.abc.AbstractIncomingMessage | None:
    """Peek at the head of ``queue`` from an independent connection (fetched unacked, requeued on close)."""
    connection = await aio_pika.connect(RABBITMQ_URL)
    try:
        channel = await connection.channel()
        q = await channel.declare_queue(queue, passive=True)
        return await q.get(no_ack=False, fail=False)
    finally:
        await connection.close()


async def _raw_depth(queue: str) -> int:
    connection = await aio_pika.connect(RABBITMQ_URL)
    try:
        channel = await connection.channel()
        q = await channel.declare_queue(queue, passive=True)
        return int(q.declaration_result.message_count or 0)
    finally:
        await connection.close()


# ------------------------------------------------------------------ publish side


async def test_publisher_confirms_and_persistent_messages(rabbit: tuple[str, BusFactory]) -> None:
    namespace, make = rabbit
    bus = await make()
    assert bus.publish_channel is not None
    underlay = await bus.publish_channel.get_underlay_channel()
    assert underlay.publisher_confirms is True
    sent = [command(f"c{i}") for i in range(5)]
    for env in sent:
        await bus.send_command(CAP, env)
    # send_command returned => confirmed => already in the durable queue, visible to any other connection
    assert await _raw_depth(namespace + Q) == 5
    head = await _raw_get(namespace + Q)
    assert head is not None
    assert head.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert head.message_id == sent[0].message_id
    assert head.headers["x-hmap-kind"] == "envelope" and head.headers["x-hmap-attempt"] == 1
    assert json.loads(head.body)["correlation_id"] == "c0"


async def test_use_after_close_and_before_start(rabbit: tuple[str, BusFactory]) -> None:
    namespace, make = rabbit
    bus = await make()
    await bus.close()
    await bus.close()
    with pytest.raises(BusClosedError):
        await bus.send_command(CAP, command())
    with pytest.raises(BusClosedError):
        await bus.start()
    with pytest.raises(RuntimeError, match="start"):
        await make_rabbit_bus(namespace).publish_event(event())


# ------------------------------------------------------------------ broker-held state


async def test_attempt_count_lives_in_the_broker(rabbit: tuple[str, BusFactory]) -> None:
    """A message nacked by one process is retried, with the next attempt number, to another process."""
    _, make = rabbit
    first = await make()
    seen: list[tuple[str, int]] = []

    async def nack_once(d: Delivery) -> None:
        seen.append(("first", d.attempt))
        await d.nack(requeue=True, delay_s=0.5)

    sub = await first.consume_commands(CAP, nack_once)
    await first.send_command(CAP, command("retry-me"))
    await wait_until(lambda: len(seen) == 1)
    await wait_until_async(lambda: _retry_len(first), 1)     # the nack has been settled: waiting in hmap.retry
    await sub.cancel()                                        # the first process goes away during the retry wait

    second = await make()

    async def take(d: Delivery) -> None:
        seen.append(("second", d.attempt))
        await d.ack()

    await second.consume_commands(CAP, take)
    await wait_until(lambda: len(seen) == 2, timeout=5)
    assert seen == [("first", 1), ("second", 2)]


async def test_dead_letters_is_non_destructive(rabbit: tuple[str, BusFactory]) -> None:
    namespace, make = rabbit
    bus = await make()

    async def reject(d: Delivery) -> None:
        await d.reject(f"bad {tag_of(d.body)}")

    await bus.consume_commands(CAP, reject, prefetch=10)
    for i in range(3):
        await bus.send_command(CAP, command(f"c{i}"))
    await wait_until_async(lambda: _dlq_len(bus), 3)
    first = await bus.dead_letters()
    second = await bus.dead_letters()
    assert [d.body["correlation_id"] for d in first] == ["c0", "c1", "c2"]       # oldest first
    assert [(d.queue, d.reason, d.attempts, d.history) for d in first] == \
        [(d.queue, d.reason, d.attempts, d.history) for d in second]
    assert first[0].queue == Q and first[0].reason == "rejected: bad c0" and first[0].attempts == 1
    assert first[0].history == ["attempt 1: rejected: bad c0"]
    assert (await bus.queue_depths())[DLQ_NAME] == 3
    assert await _raw_depth(namespace + DLQ_NAME) == 3


async def test_unparseable_message_goes_to_dlq(rabbit: tuple[str, BusFactory]) -> None:
    namespace, make = rabbit
    bus = await make()
    calls: list[Delivery] = []

    async def handler(d: Delivery) -> None:
        calls.append(d)
        await d.ack()

    await bus.consume_commands(CAP, handler)
    connection = await aio_pika.connect(RABBITMQ_URL)
    try:
        channel = await connection.channel()
        await channel.default_exchange.publish(aio_pika.Message(b"{not json", headers={"x-hmap-kind": "envelope"}),
                                               routing_key=namespace + Q)
    finally:
        await connection.close()
    await wait_until_async(lambda: _dlq_len(bus), 1)
    [dl] = await bus.dead_letters()
    assert calls == [] and dl.reason == "unparseable message" and dl.queue == Q
    assert dl.body == {"raw": "{not json"}


async def test_durable_subscriber_survives_bus_restart(rabbit: tuple[str, BusFactory]) -> None:
    """A named subscriber queue outlives the process that declared it (e.g. a manager restart)."""
    _, make = rabbit
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        got.append(tag_of(d.body))
        await d.ack()

    old = await make()
    await old.subscribe_events("task.*", handler, queue="projector")
    await old.close()
    publisher = await make()
    await publisher.publish_event(event("task.completed", "T-1"))
    await publisher.publish_event(event("task.failed", "T-2"))
    new = await make()
    await new.subscribe_events("task.*", handler, queue="projector")
    await wait_until(lambda: len(got) == 2)
    assert got == ["T-1", "T-2"]


async def test_namespace_is_cleaned_up(rabbit: tuple[str, BusFactory]) -> None:
    namespace, make = rabbit
    bus = await make()

    async def nack(d: Delivery) -> None:
        await d.nack()

    await bus.consume_commands(CAP, nack)
    await bus.subscribe_events("#", nack, queue="audit")
    await bus.subscribe_events("#", nack)
    await bus.send_command(CAP, command())
    await bus.publish_event(event())
    await wait_until_async(lambda: _dlq_len(bus), 3, timeout=5)   # command + 2 event queues
    await bus.close()
    await delete_namespace(namespace, *known_names(bus))
    for _ in range(50):                                       # the management listing can lag a little
        if not await namespace_leftovers(namespace):
            break
        await asyncio.sleep(0.2)
    assert await namespace_leftovers(namespace) == []


# ------------------------------------------------------------------ connection loss


async def _force_close_connection(connection_name: str) -> None:
    """Make the broker drop the client connection (CONNECTION_FORCED), like a network blip."""
    async with httpx.AsyncClient(base_url=RABBITMQ_MGMT_URL, auth=_mgmt_auth(), timeout=10) as client:
        for _ in range(150):                                  # new connections show up in the listing with a delay
            resp = await client.get("/api/connections", params={"columns": "name,client_properties"})
            resp.raise_for_status()
            names = [c["name"] for c in resp.json()
                     if (c.get("client_properties") or {}).get("connection_name") == connection_name]
            if names:
                for name in names:
                    await client.delete(f"/api/connections/{name}")
                return
            await asyncio.sleep(0.1)
    raise AssertionError(f"connection {connection_name!r} not found in the management API")


async def test_unacked_messages_survive_a_consumer_reconnect(rabbit: tuple[str, BusFactory]) -> None:
    """The consumer's connection drops while it holds unacked deliveries: the broker requeues them, the robust
    connection reconnects and restores the consumer, and every message is redelivered (same attempt)."""
    _, make = rabbit
    publisher = await make()
    consumer = await make(reconnect_interval_s=0.2)
    seen: list[tuple[str, bool, int]] = []

    async def handler(d: Delivery) -> None:
        seen.append((tag_of(d.body), d.redelivered, d.attempt))
        if d.redelivered:
            await d.ack()
        # first delivery: hold it unacked (as if mid-processing when the connection dropped)

    await consumer.consume_commands(CAP, handler, prefetch=10)
    tags = [f"c{i}" for i in range(5)]
    for t in tags:
        await publisher.send_command(CAP, command(t))
    await wait_until(lambda: len(seen) == 5)
    assert all(not redelivered for _, redelivered, _ in seen)
    await _force_close_connection(consumer.connection_name)
    await wait_until(lambda: len(seen) == 10, timeout=20, what="redelivery after reconnect")
    assert sorted(t for t, r, _ in seen[5:] if r) == tags
    assert all(attempt == 1 for _, _, attempt in seen)
    await settle(0.2)
    assert len(seen) == 10
    assert (await publisher.queue_depths())[Q] == 0
    await publisher.send_command(CAP, command("after"))      # the restored consumer keeps working
    await wait_until(lambda: len(seen) == 11, timeout=5)


# ------------------------------------------------------------------ broker restart


def _docker_available() -> str | None:
    if shutil.which("docker") is None:
        return "docker CLI not available"
    try:
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", RABBIT_CONTAINER],
                             capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"docker not usable: {exc}"
    if out.returncode != 0 or out.stdout.strip() != "running":
        return f"container {RABBIT_CONTAINER} is not running"
    return None


async def _wait_healthy(timeout: float = 180.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        out = await asyncio.to_thread(
            subprocess.run, ["docker", "inspect", "-f", "{{.State.Health.Status}}", RABBIT_CONTAINER],
            capture_output=True, text=True, timeout=20, check=False)
        if out.stdout.strip() == "healthy":
            return
        await asyncio.sleep(1)
    raise AssertionError(f"{RABBIT_CONTAINER} did not become healthy within {timeout}s")


@pytest.mark.slow
async def test_broker_restart_loses_no_message(rabbit: tuple[str, BusFactory]) -> None:
    reason = _docker_available()
    if reason is not None:
        pytest.skip(reason)
    namespace, make = rabbit
    bus = await make(reconnect_interval_s=1.0)
    inbox = InMemoryInboxStore()
    effects: list[str] = []

    async def handler(d: Delivery) -> None:
        effects.append(tag_of(d.body))
        await d.ack()

    sent = [command(f"c{i}") for i in range(20)]
    for env in sent:
        await bus.send_command(CAP, env)                      # confirmed => persisted before the restart
    for i in range(3):
        await bus.publish_event(event("task.completed", f"T-{i}"))  # no subscriber: dropped, not an error

    out = await asyncio.to_thread(subprocess.run, ["docker", "restart", RABBIT_CONTAINER],
                                  capture_output=True, text=True, timeout=180, check=False)
    assert out.returncode == 0, out.stderr
    await _wait_healthy()
    assert bus.connection is not None and bus.publish_channel is not None
    await asyncio.wait_for(bus.connection.ready(), 60)       # the same bus object reconnects by itself
    await asyncio.wait_for(bus.publish_channel.ready(), 60)

    assert await _raw_depth(namespace + Q) == 20             # durable queue + persistent messages survived
    await bus.consume_commands(CAP, idempotent("research-1", inbox, handler), prefetch=5)
    for env in sent[:3]:                                      # an outbox replay after the restart: duplicates
        await bus.send_command(CAP, env)
    await wait_until(lambda: len(inbox) == 20, timeout=30, what="all commands processed")
    await settle(0.3)
    assert sorted(effects) == sorted(env.correlation_id for env in sent)   # every message exactly once
    assert len(effects) == len(set(effects)) == 20
    await wait_until_async(lambda: _queue_len(bus, Q), 0)
    assert (await bus.queue_depths())[DLQ_NAME] == 0


# ------------------------------------------------------------------ helpers


async def _dlq_len(bus: RabbitBus) -> int:
    return (await bus.queue_depths())[DLQ_NAME]


async def _retry_len(bus: RabbitBus) -> int:
    return (await bus.queue_depths())[RETRY_EXCHANGE]


async def _queue_len(bus: RabbitBus, queue: str) -> int:
    return (await bus.queue_depths())[queue]


async def wait_until_async(probe: Callable[[], Awaitable[int]], expected: int, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while (value := await probe()) != expected:
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {expected}, last value {value}")
        await asyncio.sleep(0.02)

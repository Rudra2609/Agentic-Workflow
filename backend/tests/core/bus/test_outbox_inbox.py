"""Outbox publisher (crash between commit and publish, failure mid-batch) and inbox dedup (duplicate delivery)."""

import asyncio

import pytest

from hmap.core.bus.base import Bus, Delivery, capability_queue
from hmap.core.bus.inbox import InMemoryInboxStore, dedup_key, idempotent
from hmap.core.bus.outbox import InMemoryOutboxStore, OutboxPublisher
from hmap.core.contracts import DomainEvent, Envelope
from tests.core.bus._helpers import CAP, command, event, settle, tag_of, wait_until

# ------------------------------------------------------------------ stores


async def test_outbox_store_assigns_unique_increasing_seq_under_concurrency() -> None:
    store = InMemoryOutboxStore()
    seqs = await asyncio.gather(*(store.add("event", event("task.completed", f"T-{i}")) for i in range(100)))
    assert sorted(seqs) == list(range(1, 101))
    rows = await store.unpublished(limit=1000)
    assert [r.seq for r in rows] == list(range(1, 101))
    assert len(await store.unpublished(limit=10)) == 10


async def test_outbox_store_validates_rows_and_copies_bodies() -> None:
    store = InMemoryOutboxStore()
    with pytest.raises(ValueError):
        await store.add("command", command())                 # command needs a capability
    with pytest.raises(ValueError):
        await store.add("bogus", event())
    with pytest.raises(TypeError):
        await store.add("event", command())
    ev = event()
    seq = await store.add("event", ev)
    ev.data["n"] = 42                                         # mutating the caller's object does not change the row
    [row] = await store.unpublished()
    assert row.seq == seq and isinstance(row.body, DomainEvent) and row.body.data["n"] == 1
    await store.mark_published(seq)
    await store.mark_published(seq)                           # idempotent
    assert await store.unpublished() == []
    with pytest.raises(KeyError):
        await store.mark_published(999)


async def test_inbox_store_record_is_atomic_under_concurrency() -> None:
    inbox = InMemoryInboxStore()
    results = await asyncio.gather(*(inbox.record("c", "m1") for _ in range(50)))
    assert results.count(True) == 1
    assert await inbox.seen("c", "m1") and not await inbox.seen("other", "m1")
    assert await inbox.record("other", "m1") is True          # keyed per consumer


# ------------------------------------------------------------------ outbox publisher


async def _collect(bus: Bus) -> tuple[list[str], list[str]]:
    events: list[str] = []
    commands: list[str] = []

    async def on_event(d: Delivery) -> None:
        events.append(tag_of(d.body))
        await d.ack()

    async def on_command(d: Delivery) -> None:
        commands.append(tag_of(d.body))
        await d.ack()

    await bus.subscribe_events("#", on_event, queue="outbox-test")
    await bus.consume_commands(CAP, on_command, prefetch=100)
    return events, commands


async def test_outbox_crash_between_commit_and_publish(bus: Bus) -> None:
    store = InMemoryOutboxStore()
    events, commands = await _collect(bus)
    # row 1 was published before the "crash"; rows 2-4 were committed but the process died before publishing
    first = event("task.created", "T-1")
    s1 = await store.add("event", first)
    await bus.publish_event(first)
    await store.mark_published(s1)
    await store.add("event", event("task.ready", "T-2"))
    await store.add("command", command("C-3"), capability=CAP)
    await store.add("event", event("task.assigned", "T-4"))
    await wait_until(lambda: events == ["T-1"])

    publisher = OutboxPublisher(store, bus)               # fresh publisher after restart
    assert await publisher.run_once() == 3                # exactly the unpublished rows
    await wait_until(lambda: len(events) == 3 and len(commands) == 1)
    assert events == ["T-1", "T-2", "T-4"] and commands == ["C-3"]
    assert await store.unpublished() == []
    assert await publisher.run_once() == 0                # nothing replayed twice
    await settle()
    assert len(events) == 3 and len(commands) == 1


class _FlakyBus:
    """Delegates to a real bus but fails the n-th publish once (simulated broker hiccup)."""

    def __init__(self, inner: Bus, fail_on: int) -> None:
        self.inner = inner
        self.fail_on = fail_on
        self.calls = 0

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.calls == self.fail_on:
            raise ConnectionError("broker unavailable")

    async def publish_event(self, ev: DomainEvent) -> None:
        self._maybe_fail()
        await self.inner.publish_event(ev)

    async def send_command(self, capability: str, env: Envelope) -> None:
        self._maybe_fail()
        await self.inner.send_command(capability, env)


async def test_outbox_failure_mid_batch_keeps_order_and_retries_rest(bus: Bus) -> None:
    store = InMemoryOutboxStore()
    events, _ = await _collect(bus)
    for i in range(1, 5):
        await store.add("event", event("task.progress", f"T-{i}"))
    publisher = OutboxPublisher(store, _FlakyBus(bus, fail_on=3), batch_size=2)  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        await publisher.run_once()
    assert [r.seq for r in await store.unpublished()] == [3, 4]   # rows 1-2 marked; 3 failed; 4 not attempted
    assert await publisher.run_once() == 2
    await wait_until(lambda: len(events) == 4)
    assert events == ["T-1", "T-2", "T-3", "T-4"]


async def test_outbox_run_forever_and_stop(bus: Bus) -> None:
    store = InMemoryOutboxStore()
    events, _ = await _collect(bus)
    publisher = OutboxPublisher(store, bus)
    task = asyncio.create_task(publisher.run_forever(interval_s=5.0))
    await store.add("event", event("task.created", "T-1"))
    publisher.notify()                                    # don't wait for the 5 s tick
    await wait_until(lambda: events == ["T-1"])
    publisher.stop()
    await asyncio.wait_for(task, 2)


async def test_outbox_run_forever_survives_errors(bus: Bus) -> None:
    store = InMemoryOutboxStore()
    events, _ = await _collect(bus)
    await store.add("event", event("task.created", "T-1"))
    publisher = OutboxPublisher(store, _FlakyBus(bus, fail_on=1), batch_size=10)  # type: ignore[arg-type]
    task = asyncio.create_task(publisher.run_forever(interval_s=0.01))
    await wait_until(lambda: events == ["T-1"])
    publisher.stop()
    await asyncio.wait_for(task, 2)


# ------------------------------------------------------------------ inbox dedup


async def test_duplicate_command_delivery_is_processed_once(bus: Bus) -> None:
    inbox = InMemoryInboxStore()
    effects: list[str] = []

    async def handler(d: Delivery) -> None:
        effects.append(tag_of(d.body))
        await d.ack()

    await bus.consume_commands(CAP, idempotent("research-1", inbox, handler))
    dup = command("once")
    await bus.send_command(CAP, dup)
    await bus.send_command(CAP, dup)                      # same message_id (e.g. outbox replay)
    await bus.send_command(CAP, command("other"))
    await wait_until(lambda: len(inbox) == 2)
    await settle()
    assert effects == ["once", "other"]
    assert (await bus.queue_depths())[capability_queue(CAP)] == 0   # the duplicate was acked, not left behind
    assert await inbox.seen("research-1", dup.message_id)


async def test_duplicate_event_delivery_is_processed_once(bus: Bus) -> None:
    inbox = InMemoryInboxStore()
    effects: list[str] = []

    async def handler(d: Delivery) -> None:
        effects.append(dedup_key(d.body))
        await d.ack()

    await bus.subscribe_events("task.*", idempotent("projector", inbox, handler), queue="projector")
    ev = event("task.completed")
    await bus.publish_event(ev)
    await bus.publish_event(ev)
    await settle()
    await wait_until(lambda: len(effects) == 1)
    await settle()
    assert effects == [ev.event_id]
    assert (await bus.queue_depths())["projector"] == 0


async def test_crash_mid_handler_is_not_recorded_and_is_redelivered(bus: Bus) -> None:
    inbox = InMemoryInboxStore()
    runs: list[int] = []

    async def handler(d: Delivery) -> None:
        runs.append(d.attempt)
        if d.attempt == 1:
            raise RuntimeError("crashed before the effect was durable")
        await d.ack()

    await bus.consume_commands(CAP, idempotent("research-1", inbox, handler))
    sent = command()
    await bus.send_command(CAP, sent)
    await wait_until(lambda: len(inbox) == 1)
    await settle()
    assert runs == [1, 2]                                 # retried because nothing was recorded on the crash
    await bus.send_command(CAP, sent)                     # a later duplicate is skipped
    await settle()
    assert runs == [1, 2]

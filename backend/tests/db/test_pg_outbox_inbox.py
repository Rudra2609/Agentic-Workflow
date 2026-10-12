"""``PostgresOutboxStore`` / ``PostgresInboxStore``: the in-memory scenarios of ``tests/core/bus/test_outbox_inbox.py``
ported to Postgres (store semantics, publisher crash/failure recovery, inbox dedup) + concurrency on the real DB."""

import asyncio

import pytest

from hmap.core.bus.base import Bus, Delivery, capability_queue
from hmap.core.bus.inbox import dedup_key, idempotent
from hmap.core.bus.outbox import OutboxPublisher
from hmap.core.bus.pg_stores import PostgresInboxStore, PostgresOutboxStore
from hmap.core.contracts import DomainEvent, Envelope
from hmap.db import Database
from tests.core.bus._helpers import CAP, command, event, settle, tag_of, wait_until
from tests.core.bus.test_outbox_inbox import _collect, _FlakyBus

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox(db: Database) -> PostgresOutboxStore:
    return PostgresOutboxStore(db)


@pytest.fixture
def inbox(db: Database) -> PostgresInboxStore:
    return PostgresInboxStore(db)


# ------------------------------------------------------------------ stores


async def test_outbox_store_assigns_unique_increasing_seq_under_concurrency(outbox: PostgresOutboxStore) -> None:
    seqs = await asyncio.gather(*(outbox.add("event", event("task.completed", f"T-{i}")) for i in range(100)))
    assert sorted(seqs) == list(range(1, 101))
    rows = await outbox.unpublished(limit=1000)
    assert [r.seq for r in rows] == list(range(1, 101))
    assert len(await outbox.unpublished(limit=10)) == 10
    assert await outbox.unpublished(limit=0) == []


async def test_outbox_store_validates_rows_and_copies_bodies(outbox: PostgresOutboxStore) -> None:
    with pytest.raises(ValueError):
        await outbox.add("command", command())                 # command needs a capability
    with pytest.raises(ValueError):
        await outbox.add("bogus", event())
    with pytest.raises(TypeError):
        await outbox.add("event", command())
    ev = event()
    seq = await outbox.add("event", ev)
    ev.data["n"] = 42                                          # mutating the caller's object does not change the row
    [row] = await outbox.unpublished()
    assert row.seq == seq and isinstance(row.body, DomainEvent) and row.body.data["n"] == 1
    assert row.body == event().model_copy(update={"event_id": ev.event_id, "occurred_at": ev.occurred_at})
    assert row.created_at.tzinfo is not None and row.published_at is None
    await outbox.mark_published(seq)
    first = (await outbox.all_rows())[0].published_at
    await outbox.mark_published(seq)                           # idempotent: first publication time kept
    assert first is not None and (await outbox.all_rows())[0].published_at == first
    assert await outbox.unpublished() == []
    with pytest.raises(KeyError):
        await outbox.mark_published(999)


async def test_outbox_command_round_trip(outbox: PostgresOutboxStore) -> None:
    env = command("C-1")
    await outbox.add("command", env, capability=CAP)
    [row] = await outbox.unpublished()
    assert row.kind == "command" and row.capability == CAP and isinstance(row.body, Envelope)
    assert row.body == env


async def test_inbox_store_record_is_atomic_under_concurrency(inbox: PostgresInboxStore) -> None:
    results = await asyncio.gather(*(inbox.record("c", "m1") for _ in range(50)))
    assert results.count(True) == 1
    assert await inbox.seen("c", "m1") and not await inbox.seen("other", "m1")
    assert await inbox.record("other", "m1") is True          # keyed per consumer
    assert await inbox.count() == 2


# ------------------------------------------------------------------ outbox publisher


async def test_outbox_crash_between_commit_and_publish(bus: Bus, outbox: PostgresOutboxStore) -> None:
    events, commands = await _collect(bus)
    first = event("task.created", "T-1")
    s1 = await outbox.add("event", first)
    await bus.publish_event(first)
    await outbox.mark_published(s1)
    await outbox.add("event", event("task.ready", "T-2"))
    await outbox.add("command", command("C-3"), capability=CAP)
    await outbox.add("event", event("task.assigned", "T-4"))
    await wait_until(lambda: events == ["T-1"])

    publisher = OutboxPublisher(PostgresOutboxStore(outbox.db), bus)   # fresh store + publisher after "restart"
    assert await publisher.run_once() == 3
    await wait_until(lambda: len(events) == 3 and len(commands) == 1)
    assert events == ["T-1", "T-2", "T-4"] and commands == ["C-3"]
    assert await outbox.unpublished() == []
    assert await publisher.run_once() == 0
    await settle()
    assert len(events) == 3 and len(commands) == 1


async def test_outbox_failure_mid_batch_keeps_order_and_retries_rest(bus: Bus, outbox: PostgresOutboxStore) -> None:
    events, _ = await _collect(bus)
    for i in range(1, 5):
        await outbox.add("event", event("task.progress", f"T-{i}"))
    publisher = OutboxPublisher(outbox, _FlakyBus(bus, fail_on=3), batch_size=2)  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        await publisher.run_once()
    assert [r.seq for r in await outbox.unpublished()] == [3, 4]
    assert await publisher.run_once() == 2
    await wait_until(lambda: len(events) == 4)
    assert events == ["T-1", "T-2", "T-3", "T-4"]


async def test_outbox_run_forever_and_stop(bus: Bus, outbox: PostgresOutboxStore) -> None:
    events, _ = await _collect(bus)
    publisher = OutboxPublisher(outbox, bus)
    task = asyncio.create_task(publisher.run_forever(interval_s=5.0))
    await outbox.add("event", event("task.created", "T-1"))
    publisher.notify()
    await wait_until(lambda: events == ["T-1"])
    publisher.stop()
    await asyncio.wait_for(task, 2)


# ------------------------------------------------------------------ inbox dedup


async def test_duplicate_command_delivery_is_processed_once(bus: Bus, inbox: PostgresInboxStore) -> None:
    effects: list[str] = []

    async def handler(d: Delivery) -> None:
        effects.append(tag_of(d.body))
        await d.ack()

    await bus.consume_commands(CAP, idempotent("research-1", inbox, handler))
    dup = command("once")
    await bus.send_command(CAP, dup)
    await bus.send_command(CAP, dup)
    await bus.send_command(CAP, command("other"))
    await wait_until(lambda: len(effects) == 2)
    await settle(0.2)
    assert effects == ["once", "other"]
    assert await inbox.count() == 2
    assert (await bus.queue_depths())[capability_queue(CAP)] == 0
    assert await inbox.seen("research-1", dup.message_id)


async def test_duplicate_event_delivery_is_processed_once(bus: Bus, inbox: PostgresInboxStore) -> None:
    effects: list[str] = []

    async def handler(d: Delivery) -> None:
        effects.append(dedup_key(d.body))
        await d.ack()

    await bus.subscribe_events("task.*", idempotent("projector", inbox, handler), queue="projector")
    ev = event("task.completed")
    await bus.publish_event(ev)
    await wait_until(lambda: len(effects) == 1)
    await settle(0.1)
    # events are consumed with prefetch 16, so two copies in flight at once could both run the handler (documented
    # in ``idempotent``); the redelivered copy arrives after the first was recorded, as a replay would
    assert await inbox.seen("projector", ev.event_id)
    await bus.publish_event(ev)
    await settle(0.2)
    assert effects == [ev.event_id]
    assert (await bus.queue_depths())["projector"] == 0

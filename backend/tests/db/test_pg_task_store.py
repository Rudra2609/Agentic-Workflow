"""``PostgresTaskStore``: the in-memory store's behavioural tests (imported and re-run against Postgres via the
``store`` fixture below) + Postgres-specific atomicity, CAS-race, deadlock and outbox-ordering tests."""

import asyncio

import psycopg
import pytest

from hmap.core.bus.pg_stores import PostgresInboxStore
from hmap.core.contracts import TaskState
from hmap.db import Database
from hmap.manager import ConcurrencyConflict, UniqueViolation
from hmap.manager.pg_store import PostgresTaskStore, PostgresTx
from tests.core.bus._helpers import command
from tests.manager.test_store import (  # noqa: F401  (re-collected here, against the Postgres ``store`` fixture)
    _event,
    _exe,
    _task,
    test_cas_conflict,
    test_list_filters,
    test_reads_return_copies,
    test_unique_ids,
    test_unique_task_attempt,
    test_update_missing_record,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def store(db: Database) -> PostgresTaskStore:
    return PostgresTaskStore(db)


async def _count(db: Database, table: str) -> int:
    return int((await db.fetch(f"SELECT count(*) AS n FROM {table}"))[0]["n"])


# ------------------------------------------------------------------ ported (in-memory version asserts on FakeOutbox)


async def test_state_change_and_event_commit_together(store: PostgresTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
        await tx.add_event(_event())
        await tx.add_command("research.run", command("C-1"))
        assert await store.get_task("T-1") is None          # not visible outside before commit
        assert (await tx.get_task("T-1")) is not None       # tx sees its own writes
        assert await store.outbox.unpublished() == []
    assert (await store.get_task("T-1")) is not None
    rows = await store.outbox.unpublished()
    assert [(r.kind, r.capability) for r in rows] == [("event", None), ("command", "research.run")]
    assert await _count(store.db, "events") == 1 and await _count(store.db, "messages") == 1


async def test_exception_rolls_back_state_and_outbox(store: PostgresTaskStore) -> None:
    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            await tx.insert_task(_task())
            await tx.add_event(_event())
            await tx.flush_outbox()                        # even rows already INSERTed are rolled back
            raise RuntimeError("boom")
    assert await store.get_task("T-1") is None
    assert await store.outbox.all_rows() == []
    assert await _count(store.db, "events") == 0


# ------------------------------------------------------------------ Postgres specifics


async def test_unique_violation_keeps_transaction_usable(store: PostgresTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
        with pytest.raises(UniqueViolation):
            await tx.insert_task(_task())                  # savepoint rolled back, tx still alive
        await tx.insert_task(_task("T-2"))
        await tx.add_event(_event())
    assert [t.task_id for t in await store.list_tasks()] == ["T-1", "T-2"]
    assert len(await store.outbox.unpublished()) == 1


async def test_bad_outbox_rows_are_rejected_eagerly(store: PostgresTaskStore) -> None:
    with pytest.raises(ValueError):
        async with store.transaction() as tx:
            await tx.insert_task(_task())
            await tx.add_command("", command())
    assert await store.get_task("T-1") is None


async def test_concurrent_cas_exactly_one_wins(store: PostgresTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
    stale = await store.get_task("T-1")
    assert stale is not None
    a_updated, release_a = asyncio.Event(), asyncio.Event()

    async def writer_a() -> None:
        async with store.transaction() as tx:
            await tx.update_task(stale.model_copy(update={"state": TaskState.READY}), expected_version=1)
            await tx.add_event(_event(version=2))
            a_updated.set()
            await release_a.wait()                         # hold the row lock (uncommitted) while B tries

    other_process = PostgresTaskStore(store.db)            # a second store = another Manager process

    async def writer_b() -> None:
        await a_updated.wait()
        async with other_process.transaction() as tx:
            await tx.update_task(stale.model_copy(update={"state": TaskState.CANCELLED}), expected_version=1)
            await tx.add_event(_event(version=2))

    task_a = asyncio.create_task(writer_a())
    task_b = asyncio.create_task(writer_b())
    await a_updated.wait()
    await asyncio.sleep(0.2)
    assert not task_b.done()                               # B is blocked on A's row lock, not failed early
    release_a.set()
    await task_a
    with pytest.raises(ConcurrencyConflict):
        await task_b
    current = await store.get_task("T-1")
    assert current is not None and current.state == TaskState.READY and current.state_version == 2
    assert len(await store.outbox.unpublished()) == 1      # the loser's event was rolled back with it


async def test_many_racing_writers_one_winner(store: PostgresTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())

    async def attempt(i: int) -> bool:
        try:
            async with PostgresTaskStore(store.db).transaction() as tx:     # one "process" each
                await tx.update_task(_task().model_copy(update={"title": f"w{i}"}), expected_version=1)
                await tx.add_event(_event(version=2))
            return True
        except ConcurrencyConflict:
            return False

    results = await asyncio.gather(*(attempt(i) for i in range(10)))
    assert results.count(True) == 1
    current = await store.get_task("T-1")
    assert current is not None and current.state_version == 2
    assert len(await store.outbox.unpublished()) == 1


async def test_deadlock_surfaces_as_concurrency_conflict(store: PostgresTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task("T-1"))
        await tx.insert_task(_task("T-2"))
    first_locked = [asyncio.Event(), asyncio.Event()]
    stores = [PostgresTaskStore(store.db), PostgresTaskStore(store.db)]   # two "processes"

    async def writer(i: int, order: tuple[str, str]) -> bool:
        try:
            async with stores[i].transaction() as tx:
                await tx.update_task(_task(order[0]), expected_version=1)
                first_locked[i].set()
                await first_locked[1 - i].wait()
                await tx.update_task(_task(order[1]), expected_version=1)
            return True
        except ConcurrencyConflict:
            return False

    results = await asyncio.gather(writer(0, ("T-1", "T-2")), writer(1, ("T-2", "T-1")))
    assert sorted(results) == [False, True]                # Postgres picked a deadlock victim; the other committed


async def test_outbox_seq_order_is_commit_order(store: PostgresTaskStore) -> None:
    """A writer holding outbox rows uncommitted blocks later outbox writers, so readers never see a gap."""
    flushed, release = asyncio.Event(), asyncio.Event()

    async def slow_writer() -> None:
        async with store.transaction() as tx:
            await tx.insert_task(_task())
            await tx.add_event(_event("T-1"))
            await tx.flush_outbox()                        # seq allocated now; lock held until commit
            flushed.set()
            await release.wait()

    slow = asyncio.create_task(slow_writer())
    await flushed.wait()
    fast = asyncio.create_task(store.outbox.add("event", _event("T-2")))
    await asyncio.sleep(0.2)
    assert not fast.done()                                 # waits for the slow writer's commit
    assert await store.outbox.unpublished() == []
    release.set()
    await slow
    fast_seq = await fast
    rows = await store.outbox.unpublished()
    assert [r.body.aggregate_id for r in rows] == ["T-1", "T-2"] and rows[-1].seq == fast_seq


async def test_serialize_writes_mode_is_one_writer_across_processes(db: Database) -> None:
    a = PostgresTaskStore(db, local_lock=False, serialize_writes=True)
    b = PostgresTaskStore(db, local_lock=False, serialize_writes=True)
    inside = asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with a.transaction() as tx:
            inside.set()
            await asyncio.sleep(0.2)
            await tx.insert_task(_task("T-2"))
            order.append("first")

    async def second() -> None:
        await inside.wait()
        async with b.transaction() as tx:
            order.append("second")
            await tx.insert_task(_task("T-3"))

    await asyncio.gather(first(), second())
    assert order == ["first", "second"]


async def test_local_lock_runs_transactions_in_request_order(store: PostgresTaskStore) -> None:
    """Like ``InMemoryTaskStore``: one store object = one transaction at a time, FIFO (the Manager relies on it)."""
    async with store.transaction() as tx:
        await tx.insert_task(_task())
    order: list[int] = []

    async def unit(i: int) -> None:
        async with store.transaction() as tx:
            t = await tx.get_task("T-1")
            assert t is not None
            await asyncio.sleep(0.01 * (5 - i))            # later requests would overtake without the lock
            await tx.update_task(t.model_copy(update={"title": str(i)}), expected_version=t.state_version)
            order.append(i)

    await asyncio.gather(*(unit(i) for i in range(5)))
    assert order == [0, 1, 2, 3, 4]
    current = await store.get_task("T-1")
    assert current is not None and current.state_version == 6 and current.title == "4"


async def test_inbox_row_in_same_transaction(store: PostgresTaskStore) -> None:
    inbox = PostgresInboxStore(store.db)
    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            assert isinstance(tx, PostgresTx)
            assert await tx.record_inbox("manager", "M-1") is True
            await tx.insert_task(_task())
            raise RuntimeError("effect failed")
    assert not await inbox.seen("manager", "M-1")          # rolled back together with the effect
    async with store.transaction() as tx:
        assert isinstance(tx, PostgresTx)
        assert await tx.record_inbox("manager", "M-1") is True
        await tx.insert_task(_task())
    async with store.transaction() as tx:
        assert isinstance(tx, PostgresTx)
        assert await tx.record_inbox("manager", "M-1") is False   # duplicate -> effect already committed


async def test_round_trip_preserves_every_field(store: PostgresTaskStore) -> None:
    from hmap.core.contracts import ArtifactRef, ContextRef, Priority
    from tests.manager.fakes import T0

    ref = ArtifactRef(artifact_id="ART-1", artifact_type="report", version=2, uri="file://x", sha256="a" * 64,
                      media_type="text/plain", size_bytes=3, created_by="me", created_at=T0, access_scope="P-1")
    task = _task().model_copy(update={
        "title": "t", "acceptance_criteria": ["a", "b"], "inputs": {"k": [1, 2.5, None, "ü"]},
        "artifact_refs": [ref], "context_refs": [ContextRef(context_id="CTX-1", version=3)], "depends_on": ["T-0"],
        "priority": Priority.HIGH, "retry_at": T0, "last_error": {"code": "TIMEOUT"}, "rejected_by": ["a1"]})
    exe = _exe("E-1", 1).model_copy(update={"lease_until": T0, "result_refs": [ref], "evidence": [{"n": 1}]})
    async with store.transaction() as tx:
        await tx.insert_task(task)
        await tx.insert_execution(exe)
    assert await store.get_task("T-1") == task
    assert await store.get_execution("E-1") == exe


async def test_non_conflict_errors_propagate_unchanged(store: PostgresTaskStore) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        async with store.transaction() as tx:
            await tx.insert_execution(_exe("E-0", 0))       # attempt >= 1 check constraint

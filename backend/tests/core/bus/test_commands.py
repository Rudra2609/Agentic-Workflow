"""Command queues: round-trip, isolation, competing consumers, prefetch, retry/attempts, DLQ, consumer crash,
queue depths and close. Adapter-agnostic: runs against every ``bus`` fixture parameter."""

import asyncio

import pytest

from hmap.core.bus.base import DLQ_NAME, Bus, CommandHandler, Delivery, capability_queue
from hmap.core.contracts import Envelope
from tests.core.bus._helpers import CAP, MAX_ATTEMPTS, RETRY_DELAYS_S, command, reply, settle, tag_of, wait_until

Q = capability_queue(CAP)


async def test_command_round_trip_is_a_fresh_copy(bus: Bus) -> None:
    sent = command("c1")
    got: list[Delivery] = []

    async def handler(d: Delivery) -> None:
        got.append(d)
        await d.ack()

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, sent)
    await wait_until(lambda: len(got) == 1)
    d = got[0]
    assert isinstance(d.body, Envelope)
    assert d.body == sent and d.body is not sent and d.body.payload is not sent.payload
    assert d.attempt == 1 and d.redelivered is False
    depths = await bus.queue_depths()
    assert depths[Q] == 0 and depths[DLQ_NAME] == 0


async def test_reply_round_trip_on_manager_queue(bus: Bus) -> None:
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        got.append(tag_of(d.body))
        await d.ack()

    await bus.send_reply(reply("r1"))           # sent before the manager consumes: waits in hmap.manager
    assert (await bus.queue_depths())["hmap.manager"] == 1
    await bus.consume_replies(handler)
    await bus.send_reply(reply("r2"))
    await wait_until(lambda: len(got) == 2)
    assert got == ["r1", "r2"]


async def test_commands_wait_until_a_consumer_appears(bus: Bus) -> None:
    for i in range(3):
        await bus.send_command(CAP, command(f"c{i}"))
    assert (await bus.queue_depths())[Q] == 3
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        got.append(tag_of(d.body))
        await d.ack()

    await bus.consume_commands(CAP, handler, prefetch=10)
    await wait_until(lambda: len(got) == 3)
    assert got == ["c0", "c1", "c2"]                      # FIFO
    assert (await bus.queue_depths())[Q] == 0


async def test_capability_queues_are_separate(bus: Bus) -> None:
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        got.append(tag_of(d.body))
        await d.ack()

    await bus.consume_commands("other.cap", handler)
    await bus.send_command(CAP, command("mine"))
    await settle()
    assert got == []
    assert (await bus.queue_depths())[Q] == 1


async def test_competing_consumers_round_robin(bus: Bus) -> None:
    seen: dict[str, list[str]] = {"a": [], "b": []}

    def make(name: str) -> CommandHandler:
        async def handler(d: Delivery) -> None:
            seen[name].append(tag_of(d.body))
            await d.ack()
        return handler

    await bus.consume_commands(CAP, make("a"), prefetch=10)
    await bus.consume_commands(CAP, make("b"), prefetch=10)
    for i in range(6):
        await bus.send_command(CAP, command(f"c{i}"))
    await wait_until(lambda: len(seen["a"]) + len(seen["b"]) == 6)
    assert sorted(seen["a"] + seen["b"]) == [f"c{i}" for i in range(6)]   # each message to exactly one consumer
    assert len(seen["a"]) == 3 and len(seen["b"]) == 3


async def test_busy_consumer_is_skipped(bus: Bus) -> None:
    """With prefetch=1 a consumer holding an unacked message gets nothing more; the free one takes the work."""
    release = asyncio.Event()
    slow: list[str] = []
    fast: list[str] = []

    async def slow_handler(d: Delivery) -> None:
        slow.append(tag_of(d.body))
        await release.wait()
        await d.ack()

    async def fast_handler(d: Delivery) -> None:
        fast.append(tag_of(d.body))
        await d.ack()

    await bus.consume_commands(CAP, slow_handler, prefetch=1)
    await bus.send_command(CAP, command("c0"))
    await wait_until(lambda: slow == ["c0"])
    await bus.consume_commands(CAP, fast_handler, prefetch=1)
    for i in range(1, 5):
        await bus.send_command(CAP, command(f"c{i}"))
    await wait_until(lambda: len(fast) == 4)
    assert slow == ["c0"] and fast == ["c1", "c2", "c3", "c4"]
    release.set()


async def test_prefetch_bounds_unacked_deliveries(bus: Bus) -> None:
    release = asyncio.Event()
    in_flight = 0
    max_in_flight = 0
    done: list[str] = []

    async def handler(d: Delivery) -> None:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await release.wait()
        in_flight -= 1
        done.append(tag_of(d.body))
        await d.ack()

    await bus.consume_commands(CAP, handler, prefetch=2)
    for i in range(5):
        await bus.send_command(CAP, command(f"c{i}"))
    await wait_until(lambda: in_flight == 2)
    await settle()
    assert in_flight == 2
    assert (await bus.queue_depths())[Q] == 3                 # the rest wait in the queue
    release.set()
    await wait_until(lambda: len(done) == 5)
    assert max_in_flight == 2


async def test_nack_retries_with_delay_and_counts_attempts(bus: Bus) -> None:
    loop = asyncio.get_running_loop()
    attempts: list[tuple[int, bool, float]] = []

    async def handler(d: Delivery) -> None:
        attempts.append((d.attempt, d.redelivered, loop.time()))
        if d.attempt < 3:
            await d.nack(requeue=True)
        else:
            await d.ack()

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(attempts) == 3)
    await settle()
    assert [a for a, _, _ in attempts] == [1, 2, 3]
    assert all(not redelivered for _, redelivered, _ in attempts)   # a retry is a new delivery, not a requeue
    assert attempts[1][2] - attempts[0][2] >= RETRY_DELAYS_S[0] * 0.9
    assert attempts[2][2] - attempts[1][2] >= RETRY_DELAYS_S[1] * 0.9
    assert len(attempts) == 3 and (await bus.dead_letters()) == []


async def test_nack_explicit_delay_overrides_schedule(bus: Bus) -> None:
    loop = asyncio.get_running_loop()
    times: list[float] = []

    async def handler(d: Delivery) -> None:
        times.append(loop.time())
        if d.attempt == 1:
            await d.nack(requeue=True, delay_s=0.15)
        else:
            await d.ack()

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(times) == 1)
    await asyncio.sleep(0.05)
    assert len(times) == 1                                    # still waiting in the retry stage
    assert (await bus.queue_depths())[Q] == 0
    await wait_until(lambda: len(times) == 2)
    assert times[1] - times[0] >= 0.14


async def test_retries_exhausted_go_to_dlq_with_history(bus: Bus) -> None:
    calls: list[int] = []
    sent = command("poison")

    async def handler(d: Delivery) -> None:
        calls.append(d.attempt)
        await d.nack(requeue=True)

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, sent)
    await wait_until(lambda: len(calls) == MAX_ATTEMPTS)
    await settle()
    assert calls == list(range(1, MAX_ATTEMPTS + 1))          # never delivered again once dead-lettered
    [dl] = await bus.dead_letters()
    assert dl.queue == Q and dl.attempts == MAX_ATTEMPTS
    assert "exhausted" in dl.reason
    assert dl.body["message_id"] == sent.message_id and dl.body["correlation_id"] == "poison"
    assert len(dl.history) == MAX_ATTEMPTS
    depths = await bus.queue_depths()
    assert depths[DLQ_NAME] == 1 and depths[Q] == 0


async def test_handler_exception_counts_as_failed_attempt(bus: Bus) -> None:
    calls: list[int] = []

    async def handler(d: Delivery) -> None:
        calls.append(d.attempt)
        raise RuntimeError("boom")

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(calls) == MAX_ATTEMPTS)
    await settle()
    [dl] = await bus.dead_letters()
    assert dl.attempts == MAX_ATTEMPTS and any("boom" in h for h in dl.history)


async def test_reject_goes_to_dlq_immediately(bus: Bus) -> None:
    calls: list[int] = []

    async def handler(d: Delivery) -> None:
        calls.append(d.attempt)
        await d.reject("INVALID_TASK: no objective")

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command("bad"))
    await wait_until(lambda: len(calls) == 1)
    await settle()
    assert calls == [1]
    [dl] = await bus.dead_letters()
    assert dl.attempts == 1 and "INVALID_TASK" in dl.reason and dl.queue == Q
    assert dl.body["correlation_id"] == "bad"


async def test_nack_without_requeue_dead_letters(bus: Bus) -> None:
    calls: list[int] = []

    async def handler(d: Delivery) -> None:
        calls.append(d.attempt)
        await d.nack(requeue=False)

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(calls) == 1)
    await settle()
    assert calls == [1] and len(await bus.dead_letters()) == 1


async def test_consumer_crash_redelivers_to_another_consumer(bus: Bus) -> None:
    crashed = asyncio.Event()
    a_got: list[Delivery] = []
    b_got: list[Delivery] = []

    async def worker_a(d: Delivery) -> None:      # takes the message and "hangs" (never acks)
        a_got.append(d)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            crashed.set()
            raise

    async def worker_b(d: Delivery) -> None:
        b_got.append(d)
        await d.ack()

    sub_a = await bus.consume_commands(CAP, worker_a)
    await bus.send_command(CAP, command("job"))
    await wait_until(lambda: len(a_got) == 1)
    await bus.consume_commands(CAP, worker_b)
    await settle()
    assert b_got == []                            # unacked: not visible to anyone else while A holds it
    await sub_a.cancel()                          # simulated crash / connection loss
    await wait_until(lambda: len(b_got) == 1)
    d = b_got[0]
    assert tag_of(d.body) == "job"
    assert d.redelivered is True
    assert d.attempt == 1                         # a crash requeue is not a failed attempt
    assert a_got[0].redelivered is False
    await settle()
    assert (await bus.queue_depths())[Q] == 0 and (await bus.dead_letters()) == []


async def test_crash_without_other_consumer_keeps_message_queued(bus: Bus) -> None:
    got: list[Delivery] = []

    async def hold(d: Delivery) -> None:
        got.append(d)                             # returns without ack: delivery stays unacked

    sub = await bus.consume_commands(CAP, hold)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(got) == 1)
    await sub.cancel()
    assert (await bus.queue_depths())[Q] == 1
    await got[0].ack()                            # late ack from the dead consumer is ignored, not an error
    assert (await bus.queue_depths())[Q] == 1

    async def take(d: Delivery) -> None:
        got.append(d)
        await d.ack()

    await bus.consume_commands(CAP, take)
    await wait_until(lambda: len(got) == 2)
    assert got[1].redelivered is True


async def test_queue_depths(bus: Bus) -> None:
    await bus.send_command("cap.a", command("a1"))
    await bus.send_command("cap.a", command("a2"))
    await bus.send_command("cap.b", command("b1"))
    depths = await bus.queue_depths()
    assert depths[capability_queue("cap.a")] == 2
    assert depths[capability_queue("cap.b")] == 1
    assert depths[DLQ_NAME] == 0


async def test_close_is_clean_and_idempotent(bus: Bus) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(d: Delivery) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.wait_for(bus.close(), 2)
    assert cancelled.is_set()
    await bus.close()                             # second close is a no-op
    with pytest.raises(RuntimeError):
        await bus.send_command(CAP, command())

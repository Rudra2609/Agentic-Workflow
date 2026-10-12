"""Checks specific to ``InMemoryBus`` (not part of the shared adapter suite)."""

import asyncio

import pytest

from hmap.core.bus.base import RETRY_EXCHANGE, Delivery
from hmap.core.bus.memory import BusClosedError, InMemoryBus
from tests.core.bus._helpers import CAP, command, event, wait_until


def _bus_tasks() -> list[asyncio.Task[object]]:
    return [t for t in asyncio.all_tasks() if t.get_name().startswith("hmap-bus") and not t.done()]


async def test_close_cancels_handler_tasks_and_pending_retries() -> None:
    bus = InMemoryBus(retry_delays_s=(30.0,))
    hold = asyncio.Event()
    seen: list[int] = []

    async def handler(d: Delivery) -> None:
        seen.append(d.attempt)
        if d.attempt == 1 and len(seen) == 1:
            await d.nack(requeue=True)                 # schedules a 30 s retry
            return
        await hold.wait()

    await bus.consume_commands(CAP, handler, prefetch=2)
    await bus.send_command(CAP, command("retry-me"))
    await bus.send_command(CAP, command("blocked"))
    await wait_until(lambda: len(seen) == 2)
    depths = await bus.queue_depths()
    assert depths[RETRY_EXCHANGE] == 1
    assert len(_bus_tasks()) == 1
    await bus.close()
    await asyncio.sleep(0)
    assert _bus_tasks() == []
    assert (await bus.queue_depths())[RETRY_EXCHANGE] == 0
    with pytest.raises(BusClosedError):
        await bus.publish_event(event())
    with pytest.raises(BusClosedError):
        await bus.start()


async def test_retry_schedule_reuses_last_delay_and_explicit_attempt_cap() -> None:
    bus = InMemoryBus(max_attempts=5, retry_delays_s=(0.0,))
    calls: list[int] = []

    async def handler(d: Delivery) -> None:
        calls.append(d.attempt)
        await d.nack()

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(calls) == 5)
    await wait_until(lambda: bus._dlq != [])
    [dl] = await bus.dead_letters()
    assert dl.attempts == 5 and calls == [1, 2, 3, 4, 5]
    await bus.close()


@pytest.mark.parametrize("kwargs", [{"max_attempts": 0}, {"retry_delays_s": (-1.0,)}])
def test_constructor_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        InMemoryBus(**kwargs)  # type: ignore[arg-type]


async def test_prefetch_must_be_positive() -> None:
    bus = InMemoryBus()

    async def handler(d: Delivery) -> None:
        await d.ack()

    with pytest.raises(ValueError):
        await bus.consume_commands(CAP, handler, prefetch=0)
    await bus.close()


async def test_double_settle_is_an_error() -> None:
    bus = InMemoryBus()
    errors: list[Exception] = []

    async def handler(d: Delivery) -> None:
        await d.ack()
        try:
            await d.ack()
        except RuntimeError as exc:
            errors.append(exc)

    await bus.consume_commands(CAP, handler)
    await bus.send_command(CAP, command())
    await wait_until(lambda: len(errors) == 1)
    await bus.close()

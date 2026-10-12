"""Shared helpers for the bus test suite (adapter-agnostic: only the ``Bus`` protocol is used)."""

import asyncio
from collections.abc import Callable

from hmap.core.contracts import DomainEvent, Envelope, make_envelope
from hmap.core.contracts import examples as ex

# Tiny retry schedule so retry/DLQ tests run in milliseconds. Every adapter fixture must be built with these.
MAX_ATTEMPTS = 4
RETRY_DELAYS_S = (0.01, 0.02, 0.03)
CAP = "research.run"


def command(tag: str = "c1", *, receiver: str = "research-1") -> Envelope:
    """A valid ``task.assign`` command; ``tag`` goes into correlation_id so tests can tell messages apart."""
    return make_envelope(ex.MESSAGE_EXAMPLES["task.assign"], sender="manager", receiver=receiver,
                         correlation_id=tag)


def reply(tag: str = "r1") -> Envelope:
    return make_envelope(ex.MESSAGE_EXAMPLES["task.ack"], sender="research-1", correlation_id=tag)


def event(event_type: str = "task.completed", tag: str = "T-1") -> DomainEvent:
    return DomainEvent(event_type=event_type, aggregate_id=tag, data={"n": 1})


def tag_of(body: Envelope | DomainEvent) -> str:
    return body.correlation_id if isinstance(body, Envelope) else body.aggregate_id


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0, what: str = "condition") -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.002)


async def settle(seconds: float = 0.05) -> None:
    """Give the bus time to (not) deliver something — used for negative assertions."""
    await asyncio.sleep(seconds)

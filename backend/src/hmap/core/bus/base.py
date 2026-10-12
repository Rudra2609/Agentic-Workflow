"""Message-bus interface (research §22, §26, §27). Implementations: ``memory.InMemoryBus`` (tests, Phase A)
and ``rabbitmq.RabbitBus`` (Phase B). Both must pass the same test suite.

Topology (same names in both adapters):
- commands: one durable queue per capability, ``hmap.cap.<capability>`` (exchange ``hmap.commands``, direct)
- events:   topic exchange ``hmap.events``; routing key = event_type (e.g. ``task.completed``)
- retry:    failed deliveries are re-published after a delay (``hmap.retry``, TTL + dead-letter back)
- DLQ:      after ``max_attempts`` a message goes to ``hmap.dlq`` (never replayed automatically)

Semantics: at-least-once. A handler must call ``ack()`` only after its state change is durable; ``nack(requeue=True)``
schedules a delayed retry; ``reject()`` sends straight to the DLQ. Unacked deliveries are redelivered when a
consumer dies (``redelivered=True``). Consumers bound concurrency with ``prefetch``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from hmap.core.contracts import DomainEvent, Envelope

COMMANDS_EXCHANGE = "hmap.commands"
EVENTS_EXCHANGE = "hmap.events"
RETRY_EXCHANGE = "hmap.retry"
DLQ_NAME = "hmap.dlq"
DEFAULT_MAX_ATTEMPTS = 4          # first try + 3 retries (research §23)
DEFAULT_RETRY_DELAYS_S = (5.0, 30.0, 120.0)


def capability_queue(capability: str) -> str:
    return f"hmap.cap.{capability}"


class Delivery(Protocol):
    """One delivery of a message to one consumer."""

    @property
    def body(self) -> Envelope | DomainEvent: ...
    @property
    def attempt(self) -> int: ...          # 1 on first delivery
    @property
    def redelivered(self) -> bool: ...
    async def ack(self) -> None: ...
    async def nack(self, *, requeue: bool = True, delay_s: float | None = None) -> None: ...
    async def reject(self, reason: str) -> None: ...  # -> DLQ immediately


CommandHandler = Callable[[Delivery], Awaitable[None]]
EventHandler = Callable[[Delivery], Awaitable[None]]


@dataclass
class DeadLetter:
    queue: str
    body: dict[str, Any]
    reason: str
    attempts: int
    history: list[str] = field(default_factory=list)


class Subscription(Protocol):
    async def cancel(self) -> None: ...


class Bus(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def send_command(self, capability: str, envelope: Envelope) -> None:
        """Publish a command to the capability queue (publisher-confirmed in RabbitMQ)."""

    async def publish_event(self, event: DomainEvent) -> None:
        """Publish a fact to the topic exchange."""

    async def send_reply(self, envelope: Envelope) -> None:
        """Agent -> manager reports (task.ack/started/progress/result, error, agent.*) on queue ``hmap.manager``."""

    async def consume_commands(self, capability: str, handler: CommandHandler, *, prefetch: int = 1) -> Subscription:
        """Competing consumers on ``hmap.cap.<capability>``."""

    async def consume_replies(self, handler: CommandHandler, *, prefetch: int = 16) -> Subscription:
        """The manager consumes ``hmap.manager``."""

    async def subscribe_events(self, pattern: str, handler: EventHandler, *, queue: str | None = None,
                               prefetch: int = 16) -> Subscription:
        """Topic pattern like ``task.*`` or ``#``. ``queue`` names a durable subscriber; None = exclusive/temporary."""

    async def dead_letters(self) -> list[DeadLetter]:
        """Inspect the DLQ (UI / operator; replay is an explicit new execution, never automatic)."""

    async def queue_depths(self) -> dict[str, int]: ...

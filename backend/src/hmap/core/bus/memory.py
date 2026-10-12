"""In-process ``Bus`` that mimics the RabbitMQ topology in ``base.py`` (tests, Phase A).

The goal is behavioural parity with the RabbitMQ adapter so one test suite runs against both:

- **Isolation**: every message is JSON-serialised on publish and re-parsed for every delivery, so consumers never
  share objects with the publisher or with each other (like crossing a real broker).
- **Commands**: one queue per capability (``hmap.cap.<capability>``), declared on first use (send or consume), so a
  command sent before any consumer exists waits in the queue. Several consumers on one queue compete; messages are
  dispatched round-robin to consumers that have a free ``prefetch`` slot. Acks are manual.
- **Events**: topic exchange semantics (``*`` = one word, ``#`` = zero or more). Each matching subscriber queue gets
  its own copy (one copy per queue even if several of its bindings match). A named subscriber (``queue=...``) is
  durable: it keeps buffering while it has no consumer. A temporary subscriber (``queue=None``) is exclusive and is
  deleted with its subscription. Events matching no queue are dropped (unroutable), as in RabbitMQ.
- **Replies**: agents -> manager on the durable queue ``hmap.manager``.

Retry / attempt semantics (the RabbitMQ adapter derives the same numbers from the ``x-death`` count):

- ``Delivery.attempt`` is 1 on the first delivery and increases by one per *retry* (``nack(requeue=True)``).
- ``nack(requeue=True)`` at attempt ``n``: if ``n >= max_attempts`` the message goes to the DLQ ("retries
  exhausted"); otherwise it is re-queued after ``delay_s`` (if given) or ``retry_delays_s[n-1]`` (the last delay is
  reused if the schedule is shorter than ``max_attempts - 1``). While waiting it is counted under ``hmap.retry``.
  A retried delivery is a fresh publish from the retry queue, so it has ``redelivered=False``.
- ``nack(requeue=False)`` and ``reject(reason)`` dead-letter immediately.
- A handler that raises without settling its delivery is treated as ``nack(requeue=True)`` (error recorded in the
  history). A handler that returns without settling leaves the delivery unacked (it still holds a prefetch slot),
  exactly like a broker; it can be settled later.
- **Consumer loss** (``Subscription.cancel()`` / ``close()``, i.e. a simulated crash or connection drop): the
  consumer's in-flight handler tasks are cancelled and its unacked deliveries go back to the *front* of their queue
  with ``redelivered=True``. This does **not** count as an attempt (the attempt number is unchanged, as with a
  RabbitMQ requeue on connection loss); the event is recorded in the failure history. Protection against a message
  that crashes every consumer is the Manager's ack-timeout / lease logic, not the bus. Late ``ack``/``nack`` calls
  on a delivery whose consumer is gone are ignored (the broker channel would be closed).

Every DLQ entry keeps the original body (as a JSON dict), the origin queue, the reason, the attempt count and the
failure history. Nothing is ever replayed automatically.
"""

import asyncio
import itertools
import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import structlog

from hmap.core.bus.base import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAYS_S,
    DLQ_NAME,
    RETRY_EXCHANGE,
    Bus,
    CommandHandler,
    DeadLetter,
    EventHandler,
    capability_queue,
)
from hmap.core.bus.topics import topic_matches, validate_pattern
from hmap.core.contracts import DomainEvent, Envelope

MANAGER_QUEUE = "hmap.manager"
TEMP_EVENT_QUEUE_PREFIX = "hmap.events.tmp."

_log = structlog.get_logger(__name__)

_Kind = Literal["envelope", "event"]
_Handler = CommandHandler | EventHandler


class BusClosedError(RuntimeError):
    """Raised when the bus is used after ``close()``."""


@dataclass
class _Message:
    tag: int
    kind: _Kind
    raw: str                                   # JSON exactly as published; parsed afresh for every delivery
    attempt: int = 1
    redelivered: bool = False
    history: list[str] = field(default_factory=list)


@dataclass
class _Queue:
    name: str
    durable: bool
    ready: deque[_Message] = field(default_factory=deque)
    consumers: list["_Consumer"] = field(default_factory=list)
    bindings: set[str] = field(default_factory=set)     # topic patterns (event queues only)
    rr: int = 0                                         # round-robin cursor
    deleted: bool = False


class _Consumer:
    def __init__(self, bus: "InMemoryBus", queue: _Queue, handler: _Handler, prefetch: int) -> None:
        self.bus = bus
        self.queue = queue
        self.handler = handler
        self.prefetch = prefetch
        self.active = True
        self.unacked: dict[int, _MemoryDelivery] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    @property
    def has_capacity(self) -> bool:
        return self.active and len(self.unacked) < self.prefetch


class _MemoryDelivery:
    """One delivery of one message to one consumer (implements ``base.Delivery``)."""

    def __init__(self, consumer: _Consumer, message: _Message, body: Envelope | DomainEvent) -> None:
        self._consumer = consumer
        self._message = message
        self._body = body
        self._attempt = message.attempt
        self._redelivered = message.redelivered
        self.settled = False

    @property
    def body(self) -> Envelope | DomainEvent:
        return self._body

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def redelivered(self) -> bool:
        return self._redelivered

    @property
    def queue(self) -> str:
        return self._consumer.queue.name

    def _take(self) -> bool:
        """Mark settled; False if this delivery is stale (already settled, or its consumer is gone)."""
        if self.settled:
            raise RuntimeError("delivery already settled")
        self.settled = True
        consumer = self._consumer
        return consumer.active and consumer.unacked.pop(self._message.tag, None) is not None

    async def ack(self) -> None:
        if self._take():
            self._consumer.bus._pump(self._consumer.queue)

    async def nack(self, *, requeue: bool = True, delay_s: float | None = None) -> None:
        if self._take():
            self._consumer.bus._retry_or_dead_letter(self._consumer.queue, self._message, requeue=requeue,
                                                     delay_s=delay_s, note="nack")

    async def reject(self, reason: str) -> None:
        if self._take():
            msg = self._message
            msg.history.append(f"attempt {msg.attempt}: rejected: {reason}")
            self._consumer.bus._dead_letter(self._consumer.queue, msg, f"rejected: {reason}")

    async def _fail(self, exc: BaseException) -> None:
        """Handler raised without settling: same as ``nack(requeue=True)`` but with the error in the history."""
        if self.settled:
            return
        if self._take():
            self._consumer.bus._retry_or_dead_letter(self._consumer.queue, self._message, requeue=True,
                                                     delay_s=None, note=f"handler error: {exc!r}")


class _MemorySubscription:
    def __init__(self, bus: "InMemoryBus", consumer: _Consumer) -> None:
        self._bus = bus
        self._consumer = consumer

    @property
    def queue(self) -> str:
        return self._consumer.queue.name

    async def cancel(self) -> None:
        await self._bus._cancel_consumer(self._consumer)


class InMemoryBus:
    """``base.Bus`` implemented in-process. See the module docstring for the exact semantics."""

    def __init__(self, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 retry_delays_s: Sequence[float] = DEFAULT_RETRY_DELAYS_S) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if any(d < 0 for d in retry_delays_s):
            raise ValueError("retry delays must be >= 0")
        self.max_attempts = max_attempts
        self.retry_delays_s = tuple(retry_delays_s)
        self._queues: dict[str, _Queue] = {}
        self._dlq: list[DeadLetter] = []
        self._delayed: dict[int, asyncio.TimerHandle] = {}
        self._consumers: set[_Consumer] = set()
        self._tags = itertools.count(1)
        self._closed = False
        self._declare(MANAGER_QUEUE, durable=True)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        if self._closed:
            raise BusClosedError("bus is closed")

    async def close(self) -> None:
        """Cancel every consumer (unacked deliveries are requeued, in-flight handler tasks cancelled) and every
        pending delayed retry. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for handle in self._delayed.values():
            handle.cancel()
        self._delayed.clear()
        for consumer in list(self._consumers):
            await self._cancel_consumer(consumer)

    # ------------------------------------------------------------------ publish

    async def send_command(self, capability: str, envelope: Envelope) -> None:
        if not capability:
            raise ValueError("capability must be non-empty")
        self._check_open()
        self._publish(self._declare(capability_queue(capability), durable=True), "envelope",
                      envelope.model_dump_json())

    async def publish_event(self, event: DomainEvent) -> None:
        self._check_open()
        raw = event.model_dump_json()
        for queue in list(self._queues.values()):
            if any(topic_matches(p, event.event_type) for p in queue.bindings):
                self._publish(queue, "event", raw)

    async def send_reply(self, envelope: Envelope) -> None:
        self._check_open()
        self._publish(self._declare(MANAGER_QUEUE, durable=True), "envelope", envelope.model_dump_json())

    # ------------------------------------------------------------------ consume

    async def consume_commands(self, capability: str, handler: CommandHandler, *,
                               prefetch: int = 1) -> _MemorySubscription:
        if not capability:
            raise ValueError("capability must be non-empty")
        self._check_open()
        return self._add_consumer(self._declare(capability_queue(capability), durable=True), handler, prefetch)

    async def consume_replies(self, handler: CommandHandler, *, prefetch: int = 16) -> _MemorySubscription:
        return self._add_consumer(self._declare(MANAGER_QUEUE, durable=True), handler, prefetch)

    async def subscribe_events(self, pattern: str, handler: EventHandler, *, queue: str | None = None,
                               prefetch: int = 16) -> _MemorySubscription:
        validate_pattern(pattern)
        self._check_open()
        if queue is None:
            q = self._declare(f"{TEMP_EVENT_QUEUE_PREFIX}{next(self._tags)}", durable=False)
        else:
            if not queue or queue.startswith(TEMP_EVENT_QUEUE_PREFIX):
                raise ValueError(f"invalid subscriber queue name {queue!r}")
            q = self._declare(queue, durable=True)
        q.bindings.add(pattern)
        return self._add_consumer(q, handler, prefetch)

    # ------------------------------------------------------------------ inspection

    async def dead_letters(self) -> list[DeadLetter]:
        return [DeadLetter(queue=d.queue, body=dict(d.body), reason=d.reason, attempts=d.attempts,
                           history=list(d.history)) for d in self._dlq]

    async def queue_depths(self) -> dict[str, int]:
        """Ready (not in-flight) messages per declared queue, plus ``hmap.retry`` (waiting for a delayed retry)
        and ``hmap.dlq``."""
        depths = {name: len(q.ready) for name, q in self._queues.items()}
        depths[RETRY_EXCHANGE] = len(self._delayed)
        depths[DLQ_NAME] = len(self._dlq)
        return depths

    # ------------------------------------------------------------------ internals

    def _check_open(self) -> None:
        if self._closed:
            raise BusClosedError("bus is closed")

    def _declare(self, name: str, *, durable: bool) -> _Queue:
        q = self._queues.get(name)
        if q is None:
            q = self._queues[name] = _Queue(name=name, durable=durable)
        return q

    def _publish(self, queue: _Queue, kind: _Kind, raw: str) -> None:
        self._check_open()
        queue.ready.append(_Message(tag=next(self._tags), kind=kind, raw=raw))
        self._pump(queue)

    def _add_consumer(self, queue: _Queue, handler: _Handler, prefetch: int) -> _MemorySubscription:
        self._check_open()
        if prefetch < 1:
            raise ValueError("prefetch must be >= 1")
        consumer = _Consumer(self, queue, handler, prefetch)
        queue.consumers.append(consumer)
        self._consumers.add(consumer)
        self._pump(queue)
        return _MemorySubscription(self, consumer)

    def _pump(self, queue: _Queue) -> None:
        """Dispatch ready messages round-robin to consumers with a free prefetch slot. Synchronous (no await), so
        it is atomic with respect to other coroutines."""
        if self._closed or queue.deleted:
            return
        while queue.ready and queue.consumers:
            n = len(queue.consumers)
            consumer = None
            for i in range(n):
                candidate = queue.consumers[(queue.rr + i) % n]
                if candidate.has_capacity:
                    consumer = candidate
                    queue.rr = (queue.rr + i + 1) % n
                    break
            if consumer is None:
                return
            self._deliver(consumer, queue.ready.popleft())

    def _deliver(self, consumer: _Consumer, message: _Message) -> None:
        body: Envelope | DomainEvent = (Envelope.model_validate_json(message.raw) if message.kind == "envelope"
                                        else DomainEvent.model_validate_json(message.raw))
        delivery = _MemoryDelivery(consumer, message, body)
        consumer.unacked[message.tag] = delivery
        task = asyncio.get_running_loop().create_task(self._run_handler(consumer, delivery),
                                                      name=f"hmap-bus:{consumer.queue.name}:{message.tag}")
        consumer.tasks.add(task)
        task.add_done_callback(consumer.tasks.discard)

    async def _run_handler(self, consumer: _Consumer, delivery: _MemoryDelivery) -> None:
        try:
            await consumer.handler(delivery)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("bus handler raised", queue=consumer.queue.name, attempt=delivery.attempt, error=repr(exc))
            await delivery._fail(exc)

    def _retry_or_dead_letter(self, queue: _Queue, msg: _Message, *, requeue: bool, delay_s: float | None,
                              note: str) -> None:
        msg.history.append(f"attempt {msg.attempt}: {note}" + ("" if requeue else " (requeue=False)"))
        if not requeue:
            self._dead_letter(queue, msg, "nacked without requeue")
            return
        if msg.attempt >= self.max_attempts:
            self._dead_letter(queue, msg, f"retries exhausted after {msg.attempt} attempts")
            return
        if delay_s is None:
            schedule = self.retry_delays_s
            delay_s = schedule[min(msg.attempt - 1, len(schedule) - 1)] if schedule else 0.0
        msg.attempt += 1
        msg.redelivered = False
        if self._closed:
            return
        self._delayed[msg.tag] = asyncio.get_running_loop().call_later(max(0.0, delay_s), self._requeue_delayed,
                                                                       queue, msg)
        self._pump(queue)  # the nacked delivery freed a prefetch slot

    def _requeue_delayed(self, queue: _Queue, msg: _Message) -> None:
        self._delayed.pop(msg.tag, None)
        if self._closed or queue.deleted:
            return
        queue.ready.append(msg)
        self._pump(queue)

    def _dead_letter(self, queue: _Queue, msg: _Message, reason: str) -> None:
        self._dlq.append(DeadLetter(queue=queue.name, body=json.loads(msg.raw), reason=reason, attempts=msg.attempt,
                                    history=list(msg.history)))
        _log.warning("message dead-lettered", queue=queue.name, reason=reason, attempts=msg.attempt)
        self._pump(queue)

    async def _cancel_consumer(self, consumer: _Consumer) -> None:
        if not consumer.active:
            return
        consumer.active = False
        queue = consumer.queue
        self._consumers.discard(consumer)
        if consumer in queue.consumers:
            queue.consumers.remove(consumer)
            queue.rr = 0
        # requeue unacked deliveries at the front, preserving their original order
        for tag in sorted(consumer.unacked, reverse=True):
            msg = consumer.unacked[tag]._message
            msg.redelivered = True
            msg.history.append(f"attempt {msg.attempt}: consumer lost before ack; requeued")
            queue.ready.appendleft(msg)
        consumer.unacked.clear()
        tasks = [t for t in consumer.tasks if not t.done()]
        current = asyncio.current_task()
        for t in tasks:
            if t is not current:
                t.cancel()
        await asyncio.gather(*(t for t in tasks if t is not current), return_exceptions=True)
        if not queue.durable and not queue.consumers:
            queue.deleted = True
            queue.ready.clear()
            self._queues.pop(queue.name, None)
        self._pump(queue)


if TYPE_CHECKING:  # static proof that the adapter satisfies the Bus protocol
    _protocol_check: Bus = InMemoryBus()

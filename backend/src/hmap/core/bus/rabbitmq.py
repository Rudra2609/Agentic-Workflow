"""RabbitMQ ``Bus`` adapter (Phase B, research §22-27). Behaviourally identical to ``memory.InMemoryBus`` (the same
test suite runs against both); see that module for the reference semantics.

Connection: one ``aio_pika.connect_robust`` connection (auto-reconnect; channels, queues, bindings, QoS and
consumers are restored by aio-pika). One channel with **publisher confirms** is used for every publish, so
``send_command``/``publish_event``/``send_reply`` return only after the broker has taken responsibility for the
message (persistent message on a durable queue => written to disk). Every consumer gets its own channel with
``basic.qos(prefetch_count=prefetch)`` and **manual acks**.

Topology (every exchange/queue name is prefixed with ``namespace``; ``""`` in production):

- ``hmap.commands`` (direct, durable). Capability queue ``hmap.cap.<capability>`` (durable) bound with routing key
  ``<capability>``. The queue + binding are declared by ``send_command`` too, so a command sent before any consumer
  exists waits in the queue.
- ``hmap.events`` (topic, durable), routing key = ``event_type``. A named subscriber (``queue="audit"``) uses the
  durable queue ``hmap.sub.<name>`` (keeps buffering while it has no consumer); a temporary subscriber
  (``queue=None``) uses an exclusive, auto-delete queue ``hmap.events.tmp.<uuid>`` that disappears with it.
- ``hmap.manager`` (durable): agent -> manager replies, published through the default exchange.
- ``hmap.retry`` (direct, durable) + one durable TTL queue per (delay, target):
  ``hmap.retry.<ms>ms.<target-queue>`` with ``x-message-ttl=<ms>``, ``x-dead-letter-exchange=""`` and
  ``x-dead-letter-routing-key=<target-queue>``: a nacked message waits there and then dead-letters straight back to
  the queue it came from (only that queue, so other event subscribers never see a retry). ``x-expires`` removes
  idle retry queues.
- ``hmap.dlx`` (fanout, durable) -> ``hmap.dlq`` (durable). Dead letters carry the reason, attempt count, origin
  queue and failure history as headers. Nothing is replayed automatically.

Messages: JSON body (``Envelope``/``DomainEvent``), ``delivery_mode=2``, ``message_id`` = message_id/event_id,
headers ``x-hmap-kind`` (``envelope``|``event``), ``x-hmap-attempt`` (1-based) and ``x-hmap-history`` (JSON list).

Retry / attempt semantics (same numbers as the in-memory bus):

- ``nack(requeue=True)`` at attempt ``n < max_attempts``: re-published (confirmed) to the retry queue for the delay
  (``delay_s`` or ``retry_delays_s[n-1]``, last delay reused) with ``x-hmap-attempt = n+1`` and the history entry,
  then the original is acked. A delay of 0 re-publishes straight to the origin queue. The retried delivery is a new
  enqueue, so ``redelivered=False``. At ``n >= max_attempts`` -> DLQ ("retries exhausted after n attempts").
- ``nack(requeue=False)`` / ``reject(reason)`` -> DLQ. A handler that raises -> ``nack(requeue=True)``.
- Consumer loss (``Subscription.cancel()``, ``close()``, a dropped connection): the consumer's handler tasks are
  cancelled and its channel closed, so the broker requeues every unacked delivery with ``redelivered=True`` and
  the SAME attempt (headers unchanged). Late ``ack``/``nack`` calls on such a stale delivery are ignored.
- Every settlement that moves a message (retry, DLQ) publishes the new copy *before* acking the original: a crash in
  between yields a duplicate, never a loss (consumers deduplicate with ``inbox.idempotent``).

Logical names: ``queue_depths()`` and ``DeadLetter.queue`` use the namespace-free names of the in-memory bus
(``hmap.cap.x``, ``hmap.manager``, the subscriber name such as ``audit``, ``hmap.retry`` = all retry queues summed,
``hmap.dlq``) and only list queues this bus instance declared.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

import aio_pika
import aiormq
import structlog
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustExchange,
    AbstractRobustQueue,
    DeliveryMode,
    ExchangeType,
    HeadersType,
)
from aiormq.abc import AbstractChannel as RawChannel

from hmap.core.bus.base import (
    COMMANDS_EXCHANGE,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAYS_S,
    DLQ_NAME,
    EVENTS_EXCHANGE,
    RETRY_EXCHANGE,
    Bus,
    CommandHandler,
    DeadLetter,
    EventHandler,
    capability_queue,
)
from hmap.core.bus.memory import MANAGER_QUEUE, TEMP_EVENT_QUEUE_PREFIX, BusClosedError
from hmap.core.bus.topics import validate_pattern
from hmap.core.contracts import DomainEvent, Envelope

DLX_EXCHANGE = "hmap.dlx"
SUBSCRIBER_QUEUE_PREFIX = "hmap.sub."

H_KIND = "x-hmap-kind"
H_ATTEMPT = "x-hmap-attempt"
H_HISTORY = "x-hmap-history"
H_ORIGIN = "x-hmap-origin-queue"
H_REASON = "x-hmap-reason"

_log = structlog.get_logger(__name__)

_Kind = Literal["envelope", "event"]
_Handler = CommandHandler | EventHandler


def _header_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def _header_int(value: Any, default: int) -> int:
    try:
        return int(_header_str(value, str(default)))
    except ValueError:
        return default


def _header_history(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(_header_str(value))
    except ValueError:
        return [_header_str(value)]
    return [str(h) for h in parsed] if isinstance(parsed, list) else [str(parsed)]


class _Consumer:
    def __init__(self, bus: "RabbitBus", logical: str, physical: str, handler: _Handler, prefetch: int,
                 temporary: bool) -> None:
        self.bus = bus
        self.logical = logical
        self.physical = physical
        self.handler = handler
        self.prefetch = prefetch
        self.temporary = temporary
        self.channel: AbstractRobustChannel | None = None
        self.active = True
        self.unacked: set[_RabbitDelivery] = set()
        self.tasks: set[asyncio.Task[None]] = set()


class _RabbitDelivery:
    """One delivery of one message to one consumer (implements ``base.Delivery``)."""

    def __init__(self, consumer: _Consumer, message: AbstractIncomingMessage, body: Envelope | DomainEvent | None,
                 kind: _Kind) -> None:
        headers = message.headers or {}
        self._consumer = consumer
        self._message = message
        self._body = body
        self.kind = kind
        self._attempt = max(1, _header_int(headers.get(H_ATTEMPT), 1))
        self._redelivered = bool(message.redelivered)
        self.history = _header_history(headers.get(H_HISTORY))
        self.settled = False

    @property
    def body(self) -> Envelope | DomainEvent:
        if self._body is None:
            raise RuntimeError("unparseable message has no body")
        return self._body

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def redelivered(self) -> bool:
        return self._redelivered

    @property
    def queue(self) -> str:
        return self._consumer.logical

    @property
    def message(self) -> AbstractIncomingMessage:
        return self._message

    @property
    def consumer(self) -> _Consumer:
        return self._consumer

    def _take(self) -> bool:
        """Mark settled; False if this delivery is stale (its consumer/channel is gone)."""
        if self.settled:
            raise RuntimeError("delivery already settled")
        self.settled = True
        consumer = self._consumer
        consumer.unacked.discard(self)
        return consumer.active and not self._message_channel_closed()

    def _message_channel_closed(self) -> bool:
        try:
            return bool(self._message.channel.is_closed)
        except aiormq.exceptions.ChannelInvalidStateError:
            return True

    async def ack(self) -> None:
        if self._take():
            await self._consumer.bus._broker_ack(self)

    async def nack(self, *, requeue: bool = True, delay_s: float | None = None) -> None:
        if self._take():
            await self._consumer.bus._retry_or_dead_letter(self, requeue=requeue, delay_s=delay_s, note="nack")

    async def reject(self, reason: str) -> None:
        if self._take():
            history = [*self.history, f"attempt {self._attempt}: rejected: {reason}"]
            await self._consumer.bus._dead_letter(self, f"rejected: {reason}", history)

    async def _fail(self, exc: BaseException) -> None:
        """Handler raised without settling: same as ``nack(requeue=True)`` but with the error in the history."""
        if self.settled:
            return
        if self._take():
            await self._consumer.bus._retry_or_dead_letter(self, requeue=True, delay_s=None,
                                                           note=f"handler error: {exc!r}")


class _RabbitSubscription:
    def __init__(self, bus: "RabbitBus", consumer: _Consumer) -> None:
        self._bus = bus
        self._consumer = consumer

    @property
    def queue(self) -> str:
        return self._consumer.logical

    async def cancel(self) -> None:
        await self._bus._cancel_consumer(self._consumer)


class RabbitBus:
    """``base.Bus`` on RabbitMQ. See the module docstring for topology and semantics.

    ``await bus.start()`` connects (fails fast if the broker is unreachable) and declares the static topology;
    ``await bus.close()`` cancels consumers (unacked deliveries go back to their queues) and closes the connection.
    """

    def __init__(self, url: str, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 retry_delays_s: Sequence[float] = DEFAULT_RETRY_DELAYS_S, namespace: str = "",
                 connection_name: str = "hmap-bus", reconnect_interval_s: float = 2.0,
                 publish_timeout_s: float = 30.0) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if any(d < 0 for d in retry_delays_s):
            raise ValueError("retry delays must be >= 0")
        self.url = url
        self.max_attempts = max_attempts
        self.retry_delays_s = tuple(retry_delays_s)
        self.namespace = namespace
        self.connection_name = connection_name
        self.reconnect_interval_s = reconnect_interval_s
        self.publish_timeout_s = publish_timeout_s
        self._connection: AbstractRobustConnection | None = None
        self._pub: AbstractRobustChannel | None = None
        self._commands_x: AbstractRobustExchange | None = None
        self._events_x: AbstractRobustExchange | None = None
        self._retry_x: AbstractRobustExchange | None = None
        self._dlx: AbstractRobustExchange | None = None
        self._queues: dict[str, str] = {}             # logical name -> physical name (for queue_depths)
        self._declared: dict[str, AbstractRobustQueue] = {}   # physical queues declared on the publish channel
        self._retry_queues: set[str] = set()          # physical retry queue names
        self._consumers: set[_Consumer] = set()
        self._declare_lock = asyncio.Lock()
        self._inspect_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._closed = False

    # ------------------------------------------------------------------ names

    def _name(self, logical: str) -> str:
        return f"{self.namespace}{logical}"

    def _logical(self, physical: str) -> str:
        return physical[len(self.namespace):] if physical.startswith(self.namespace) else physical

    @property
    def connection(self) -> AbstractRobustConnection | None:
        return self._connection

    @property
    def publish_channel(self) -> AbstractRobustChannel | None:
        return self._pub

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._check_open()
        async with self._start_lock:
            if self._connection is not None:
                return
            connection = await aio_pika.connect_robust(
                self.url, client_properties={"connection_name": self.connection_name},
                reconnect_interval=self.reconnect_interval_s)
            try:
                pub = await connection.channel(publisher_confirms=True, on_return_raises=True)
                self._commands_x = await pub.declare_exchange(self._name(COMMANDS_EXCHANGE), ExchangeType.DIRECT,
                                                              durable=True)
                self._events_x = await pub.declare_exchange(self._name(EVENTS_EXCHANGE), ExchangeType.TOPIC,
                                                            durable=True)
                self._retry_x = await pub.declare_exchange(self._name(RETRY_EXCHANGE), ExchangeType.DIRECT,
                                                           durable=True)
                self._dlx = await pub.declare_exchange(self._name(DLX_EXCHANGE), ExchangeType.FANOUT, durable=True)
                dlq = await pub.declare_queue(self._name(DLQ_NAME), durable=True)
                await dlq.bind(self._dlx, routing_key="")
                self._declared[dlq.name] = dlq
                manager = await pub.declare_queue(self._name(MANAGER_QUEUE), durable=True)
                self._declared[manager.name] = manager
                self._queues[MANAGER_QUEUE] = manager.name
            except BaseException:
                await connection.close()
                raise
            self._connection = connection
            self._pub = pub

    async def close(self) -> None:
        """Cancel every consumer (in-flight handler tasks cancelled, unacked deliveries requeued by the broker) and
        close the connection. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for consumer in list(self._consumers):
            await self._cancel_consumer(consumer)
        connection, self._connection = self._connection, None
        self._pub = None
        if connection is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(connection.close(), 10)

    # ------------------------------------------------------------------ publish

    async def send_command(self, capability: str, envelope: Envelope) -> None:
        if not capability:
            raise ValueError("capability must be non-empty")
        self._require_pub()
        await self._declare_capability(capability)
        assert self._commands_x is not None
        await self._publish(self._commands_x, capability, envelope.model_dump_json().encode(),
                            self._headers("envelope", 1, []), envelope.message_id, mandatory=True)

    async def publish_event(self, event: DomainEvent) -> None:
        self._require_pub()
        assert self._events_x is not None
        await self._publish(self._events_x, event.event_type, event.model_dump_json().encode(),
                            self._headers("event", 1, []), event.event_id, mandatory=False)

    async def send_reply(self, envelope: Envelope) -> None:
        pub = self._require_pub()
        await self._publish(pub.default_exchange, self._name(MANAGER_QUEUE),
                            envelope.model_dump_json().encode(), self._headers("envelope", 1, []),
                            envelope.message_id, mandatory=True)

    # ------------------------------------------------------------------ consume

    async def consume_commands(self, capability: str, handler: CommandHandler, *,
                               prefetch: int = 1) -> _RabbitSubscription:
        if not capability:
            raise ValueError("capability must be non-empty")
        self._check_prefetch(prefetch)
        self._require_pub()
        await self._declare_capability(capability)
        logical = capability_queue(capability)
        return await self._add_consumer(logical, self._name(logical), handler, prefetch,
                                        bindings=[(self._name(COMMANDS_EXCHANGE), capability)], temporary=False)

    async def consume_replies(self, handler: CommandHandler, *, prefetch: int = 16) -> _RabbitSubscription:
        self._check_prefetch(prefetch)
        self._require_pub()
        return await self._add_consumer(MANAGER_QUEUE, self._name(MANAGER_QUEUE), handler, prefetch, bindings=[],
                                        temporary=False)

    async def subscribe_events(self, pattern: str, handler: EventHandler, *, queue: str | None = None,
                               prefetch: int = 16) -> _RabbitSubscription:
        validate_pattern(pattern)
        self._check_prefetch(prefetch)
        self._require_pub()
        events = self._name(EVENTS_EXCHANGE)
        if queue is None:
            logical = f"{TEMP_EVENT_QUEUE_PREFIX}{uuid.uuid4().hex}"
            return await self._add_consumer(logical, self._name(logical), handler, prefetch,
                                            bindings=[(events, pattern)], temporary=True)
        if not queue or queue.startswith(TEMP_EVENT_QUEUE_PREFIX):
            raise ValueError(f"invalid subscriber queue name {queue!r}")
        return await self._add_consumer(queue, self._name(f"{SUBSCRIBER_QUEUE_PREFIX}{queue}"), handler, prefetch,
                                        bindings=[(events, pattern)], temporary=False)

    # ------------------------------------------------------------------ inspection

    async def dead_letters(self, limit: int = 10_000) -> list[DeadLetter]:
        """Read (without consuming) up to ``limit`` DLQ messages, oldest first: they are fetched unacked with
        ``basic.get`` and returned to the queue in their original order when the inspection channel closes."""
        self._require_pub()
        out: list[DeadLetter] = []
        async with self._inspect_lock:
            ch = await self._raw_channel()
            try:
                while len(out) < limit:
                    msg = await ch.basic_get(self._name(DLQ_NAME), no_ack=False)
                    if isinstance(msg.delivery, aiormq.spec.Basic.GetEmpty):
                        break
                    out.append(self._to_dead_letter(msg.body, msg.header.properties.headers or {}))
            finally:
                with contextlib.suppress(Exception):
                    await ch.close()
        return out

    async def queue_depths(self) -> dict[str, int]:
        """Ready (not in-flight) messages per queue declared by this bus, plus ``hmap.retry`` (all retry queues
        summed: messages waiting for a delayed retry) and ``hmap.dlq``."""
        self._require_pub()
        depths: dict[str, int] = {}
        async with self._inspect_lock:
            holder: list[RawChannel] = [await self._raw_channel()]
            try:
                for logical, physical in list(self._queues.items()):
                    depths[logical] = await self._count(holder, physical) or 0
                waiting = 0
                for physical in sorted(self._retry_queues):
                    n = await self._count(holder, physical)
                    if n is None:                      # expired (x-expires): forget it
                        self._retry_queues.discard(physical)
                        self._declared.pop(physical, None)
                    else:
                        waiting += n
                depths[RETRY_EXCHANGE] = waiting
                depths[DLQ_NAME] = await self._count(holder, self._name(DLQ_NAME)) or 0
            finally:
                with contextlib.suppress(Exception):
                    await holder[0].close()
        return depths

    # ------------------------------------------------------------------ internals: plumbing

    def _check_open(self) -> None:
        if self._closed:
            raise BusClosedError("bus is closed")

    @staticmethod
    def _check_prefetch(prefetch: int) -> None:
        if prefetch < 1:
            raise ValueError("prefetch must be >= 1")

    def _require_pub(self) -> AbstractRobustChannel:
        self._check_open()
        if self._pub is None:
            raise RuntimeError("RabbitBus.start() has not been called")
        return self._pub

    def _require_connection(self) -> AbstractRobustConnection:
        self._check_open()
        if self._connection is None:
            raise RuntimeError("RabbitBus.start() has not been called")
        return self._connection

    async def _raw_channel(self) -> RawChannel:
        """A plain (non-robust) aiormq channel for inspection: a failed passive declare closes it without
        triggering aio-pika's channel restore."""
        connection = self._require_connection()
        await connection.ready()
        transport = connection.transport
        if transport is None:
            raise ConnectionError("RabbitMQ connection is not established")
        return await transport.connection.channel(publisher_confirms=False)

    async def _count(self, holder: list[RawChannel], physical: str) -> int | None:
        """Ready-message count of ``physical`` via a passive declare; None if the queue does not exist."""
        try:
            ok = await holder[0].queue_declare(physical, passive=True)
        except aiormq.exceptions.ChannelNotFoundEntity:
            holder[0] = await self._raw_channel()      # a 404 closes the channel
            return None
        return int(ok.message_count or 0)

    @staticmethod
    def _headers(kind: _Kind, attempt: int, history: list[str]) -> HeadersType:
        return {H_KIND: kind, H_ATTEMPT: attempt, H_HISTORY: json.dumps(history)}

    async def _publish(self, exchange: aio_pika.abc.AbstractExchange, routing_key: str, body: bytes,
                       headers: HeadersType, message_id: str | None, *, mandatory: bool) -> None:
        """Persistent publish on the confirm channel; returns only after the broker's confirm (raises on
        nack/return/timeout)."""
        message = aio_pika.Message(body, headers=headers, delivery_mode=DeliveryMode.PERSISTENT,
                                   content_type="application/json", message_id=message_id)
        await exchange.publish(message, routing_key=routing_key, mandatory=mandatory,
                               timeout=self.publish_timeout_s)

    async def _declare_capability(self, capability: str) -> None:
        logical = capability_queue(capability)
        physical = self._name(logical)
        if physical in self._declared:
            return
        pub = self._require_pub()
        async with self._declare_lock:
            if physical in self._declared:
                return
            assert self._commands_x is not None
            q = await pub.declare_queue(physical, durable=True)
            await q.bind(self._commands_x, routing_key=capability)
            self._declared[physical] = q
            self._queues[logical] = physical

    async def _retry_queue(self, target_physical: str, delay_ms: int) -> str:
        physical = self._name(f"{RETRY_EXCHANGE}.{delay_ms}ms.{self._logical(target_physical)}")
        if physical in self._declared:
            return physical
        pub = self._require_pub()
        async with self._declare_lock:
            if physical not in self._declared:
                assert self._retry_x is not None
                q = await pub.declare_queue(physical, durable=True, arguments={
                    "x-message-ttl": delay_ms,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": target_physical,
                    "x-expires": max(2 * delay_ms, delay_ms + 60_000),
                })
                await q.bind(self._retry_x, routing_key=physical)
                self._declared[physical] = q
                self._retry_queues.add(physical)
        return physical

    # ------------------------------------------------------------------ internals: consumers

    async def _add_consumer(self, logical: str, physical: str, handler: _Handler, prefetch: int, *,
                            bindings: list[tuple[str, str]], temporary: bool) -> _RabbitSubscription:
        connection = self._require_connection()
        consumer = _Consumer(self, logical, physical, handler, prefetch, temporary)
        channel = await connection.channel(publisher_confirms=False)
        consumer.channel = channel
        try:
            await channel.set_qos(prefetch_count=prefetch)
            if temporary:
                queue = await channel.declare_queue(physical, durable=False, exclusive=True, auto_delete=True)
            else:
                queue = await channel.declare_queue(physical, durable=True)
            for exchange, routing_key in bindings:
                await queue.bind(exchange, routing_key=routing_key)
            self._queues[logical] = physical
            self._consumers.add(consumer)

            async def on_message(message: AbstractIncomingMessage) -> None:
                self._on_message(consumer, message)

            await queue.consume(on_message, no_ack=False)
        except BaseException:
            self._consumers.discard(consumer)
            if temporary:
                self._queues.pop(logical, None)
            consumer.active = False
            with contextlib.suppress(Exception):
                await channel.close()
            raise
        if self._closed:                                   # close() raced with this subscribe
            await self._cancel_consumer(consumer)
            raise BusClosedError("bus is closed")
        return _RabbitSubscription(self, consumer)

    def _on_message(self, consumer: _Consumer, message: AbstractIncomingMessage) -> None:
        if not consumer.active:
            return            # left unacked: the broker requeues it when the consumer's channel closes
        headers = message.headers or {}
        kind = _header_str(headers.get(H_KIND), "envelope")
        try:
            body: Envelope | DomainEvent
            if kind == "envelope":
                body = Envelope.model_validate_json(message.body)
            elif kind == "event":
                body = DomainEvent.model_validate_json(message.body)
            else:
                raise ValueError(f"unknown message kind {kind!r}")
        except Exception as exc:
            _log.error("unparseable bus message", queue=consumer.logical, error=repr(exc))
            bad = _RabbitDelivery(consumer, message, None, "event" if kind == "event" else "envelope")
            bad.settled = True
            history = [*bad.history, f"attempt {bad.attempt}: unparseable: {exc!r}"]
            self._spawn(consumer, self._dead_letter(bad, "unparseable message", history), message)
            return
        delivery = _RabbitDelivery(consumer, message, body, "envelope" if kind == "envelope" else "event")
        consumer.unacked.add(delivery)
        self._spawn(consumer, self._run_handler(consumer, delivery), message)

    def _spawn(self, consumer: _Consumer, coro: Any, message: AbstractIncomingMessage) -> None:
        task: asyncio.Task[None] = asyncio.get_running_loop().create_task(
            coro, name=f"hmap-bus:{consumer.logical}:{message.delivery_tag}")
        consumer.tasks.add(task)
        task.add_done_callback(consumer.tasks.discard)

    async def _run_handler(self, consumer: _Consumer, delivery: _RabbitDelivery) -> None:
        try:
            await consumer.handler(delivery)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("bus handler raised", queue=consumer.logical, attempt=delivery.attempt, error=repr(exc))
            await delivery._fail(exc)

    async def _cancel_consumer(self, consumer: _Consumer) -> None:
        if not consumer.active:
            return
        consumer.active = False
        self._consumers.discard(consumer)
        current = asyncio.current_task()
        tasks = [t for t in consumer.tasks if not t.done() and t is not current]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        consumer.unacked.clear()
        if consumer.channel is not None:
            # closing the channel makes the broker requeue every unacked delivery (redelivered=True, same attempt)
            # and, for a temporary queue, deletes it (auto-delete, last consumer gone)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(consumer.channel.close(), 10)
        if consumer.temporary:
            self._queues.pop(consumer.logical, None)

    # ------------------------------------------------------------------ internals: settlement

    async def _broker_ack(self, delivery: _RabbitDelivery) -> None:
        try:
            await delivery.message.ack()
        except Exception as exc:            # channel gone: the broker has requeued it, a duplicate will follow
            _log.warning("ack failed; message will be redelivered", queue=delivery.queue, error=repr(exc))

    async def _broker_requeue(self, delivery: _RabbitDelivery) -> None:
        with contextlib.suppress(Exception):
            await delivery.message.nack(requeue=True)

    async def _retry_or_dead_letter(self, delivery: _RabbitDelivery, *, requeue: bool, delay_s: float | None,
                                    note: str) -> None:
        attempt = delivery.attempt
        history = [*delivery.history, f"attempt {attempt}: {note}" + ("" if requeue else " (requeue=False)")]
        if not requeue:
            await self._dead_letter(delivery, "nacked without requeue", history)
            return
        if attempt >= self.max_attempts:
            await self._dead_letter(delivery, f"retries exhausted after {attempt} attempts", history)
            return
        if delay_s is None:
            schedule = self.retry_delays_s
            delay_s = schedule[min(attempt - 1, len(schedule) - 1)] if schedule else 0.0
        delay_ms = max(0, round(delay_s * 1000))
        target = delivery.consumer.physical
        headers = self._headers(delivery.kind, attempt + 1, history)
        try:
            pub = self._require_pub()
            if delay_ms == 0:
                await self._publish(pub.default_exchange, target, delivery.message.body, headers,
                                    delivery.message.message_id, mandatory=False)
            else:
                retry_queue = await self._retry_queue(target, delay_ms)
                assert self._retry_x is not None
                await self._publish(self._retry_x, retry_queue, delivery.message.body, headers,
                                    delivery.message.message_id, mandatory=True)
        except Exception as exc:
            _log.error("retry publish failed; requeueing", queue=delivery.queue, error=repr(exc))
            await self._broker_requeue(delivery)
            return
        await self._broker_ack(delivery)

    async def _dead_letter(self, delivery: _RabbitDelivery, reason: str, history: list[str]) -> None:
        headers = self._headers(delivery.kind, delivery.attempt, history)
        headers[H_ORIGIN] = delivery.queue
        headers[H_REASON] = reason
        try:
            self._require_pub()
            assert self._dlx is not None
            await self._publish(self._dlx, "", delivery.message.body, headers, delivery.message.message_id,
                                mandatory=True)
        except Exception as exc:
            _log.error("dead-letter publish failed; requeueing", queue=delivery.queue, error=repr(exc))
            await self._broker_requeue(delivery)
            return
        _log.warning("message dead-lettered", queue=delivery.queue, reason=reason, attempts=delivery.attempt)
        await self._broker_ack(delivery)

    @staticmethod
    def _to_dead_letter(body: bytes, headers: dict[str, Any]) -> DeadLetter:
        try:
            parsed = json.loads(body)
            payload: dict[str, Any] = parsed if isinstance(parsed, dict) else {"value": parsed}
        except ValueError:
            payload = {"raw": body.decode("utf-8", errors="replace")}
        return DeadLetter(queue=_header_str(headers.get(H_ORIGIN), "?"), body=payload,
                          reason=_header_str(headers.get(H_REASON), "unknown"),
                          attempts=_header_int(headers.get(H_ATTEMPT), 1),
                          history=_header_history(headers.get(H_HISTORY)))


if TYPE_CHECKING:  # static proof that the adapter satisfies the Bus protocol
    _protocol_check: Bus = RabbitBus("amqp://")

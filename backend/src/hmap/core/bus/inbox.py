"""Inbox deduplication (research §24): an in-memory ``InboxStore`` and the ``idempotent`` handler wrapper.

The bus is at-least-once (outbox replays, consumer crashes, retries), so every consumer must tolerate duplicates.
The dedup key is ``(consumer_id, message_id)`` for an ``Envelope`` and ``(consumer_id, event_id)`` for a
``DomainEvent``.
"""

import asyncio

from hmap.core.bus.base import CommandHandler, Delivery
from hmap.core.bus.stores import InboxStore
from hmap.core.contracts import DomainEvent, Envelope


class InMemoryInboxStore:
    """``InboxStore`` kept in a set. ``record`` is a check-and-insert with no ``await`` in between, so it is atomic
    under asyncio (the lock just makes that explicit); exactly one of several concurrent callers gets ``True``."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def seen(self, consumer_id: str, message_id: str) -> bool:
        return (consumer_id, message_id) in self._seen

    async def record(self, consumer_id: str, message_id: str) -> bool:
        async with self._lock:
            key = (consumer_id, message_id)
            if key in self._seen:
                return False
            self._seen.add(key)
            return True

    def __len__(self) -> int:
        return len(self._seen)


def dedup_key(body: Envelope | DomainEvent) -> str:
    """The id a consumer deduplicates on: ``message_id`` (Envelope) or ``event_id`` (DomainEvent)."""
    return body.message_id if isinstance(body, Envelope) else body.event_id


class _InboxDelivery:
    """Wraps a delivery so that ``ack()`` first records the message in the inbox, then acks the real delivery."""

    def __init__(self, inner: Delivery, consumer_id: str, store: InboxStore) -> None:
        self._inner = inner
        self._consumer_id = consumer_id
        self._store = store

    @property
    def body(self) -> Envelope | DomainEvent:
        return self._inner.body

    @property
    def attempt(self) -> int:
        return self._inner.attempt

    @property
    def redelivered(self) -> bool:
        return self._inner.redelivered

    async def ack(self) -> None:
        # If record() raises, the delivery stays unacked and is redelivered: the effect may then be re-applied,
        # which is the documented at-least-once window of the non-transactional (in-memory) variant.
        await self._store.record(self._consumer_id, dedup_key(self._inner.body))
        await self._inner.ack()

    async def nack(self, *, requeue: bool = True, delay_s: float | None = None) -> None:
        await self._inner.nack(requeue=requeue, delay_s=delay_s)

    async def reject(self, reason: str) -> None:
        await self._inner.reject(reason)


def idempotent(consumer_id: str, inbox_store: InboxStore, handler: CommandHandler) -> CommandHandler:
    """Wrap a command/event handler so each message is *processed* at most once per ``consumer_id``.

    - Already in the inbox (duplicate delivery) -> ``ack()`` and skip; the handler is not called.
    - Otherwise the handler runs with a wrapped delivery whose ``ack()`` **first records** the message id in the
      inbox and **then** acks the broker delivery. ``nack``/``reject`` pass straight through and record nothing.
    - If the handler raises (or the process crashes) before acking, nothing is recorded and the bus redelivers.

    Ordering trade-off: the handler is expected to make its state change durable *before* calling ``ack()``, so the
    order is effect -> inbox record -> broker ack.

    - crash after the effect but before the record: the message is redelivered and the effect is **applied again**
      (the handler's own effect must therefore be idempotent or naturally keyed, e.g. an upsert by execution_id);
    - crash after the record but before the broker ack: the redelivery is recognised as a duplicate and skipped.

    Recording *before* the handler would instead risk **losing** work (recorded, then crash mid-handler, then the
    redelivery is skipped), which is worse than a duplicate. The Postgres ``InboxStore`` closes the remaining window
    by inserting the inbox row in the **same transaction** as the handler's effect (research §24), so a duplicate
    key there means "effect already committed". Two copies of the same message processed *concurrently* (both
    unseen at start) can also both run the handler; only the first ``record`` wins.
    """

    async def wrapper(delivery: Delivery) -> None:
        if await inbox_store.seen(consumer_id, dedup_key(delivery.body)):
            await delivery.ack()
            return
        await handler(_InboxDelivery(delivery, consumer_id, inbox_store))

    return wrapper

"""Transactional outbox (research §22): an in-memory ``OutboxStore`` and the ``OutboxPublisher`` that drains it.

The Manager writes its events/commands to the outbox in the same transaction as the state change; the publisher
later pushes unpublished rows to the bus **in ``seq`` order** and marks each one published *after* the bus accepted
it. A crash between commit and publish (or between publish and mark) means the row is published again on the next
run: delivery is at-least-once, so consumers deduplicate with the inbox (``inbox.idempotent``).
"""

import asyncio
import contextlib
import dataclasses
from collections.abc import Sequence

import structlog

from hmap.core.bus.base import Bus
from hmap.core.bus.stores import OutboxRow, OutboxStore
from hmap.core.contracts import DomainEvent, Envelope, utcnow

_log = structlog.get_logger(__name__)

KIND_EVENT = "event"
KIND_COMMAND = "command"


class InMemoryOutboxStore:
    """``OutboxStore`` kept in a dict. Bodies are deep-copied on the way in and out so callers cannot mutate rows.
    Every method body runs without an ``await`` between read and write, so it is atomic under asyncio; the lock
    only serialises callers explicitly (and keeps the shape of the Postgres version)."""

    def __init__(self) -> None:
        self._rows: dict[int, OutboxRow] = {}
        self._next_seq = 1
        self._lock = asyncio.Lock()

    async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None = None) -> int:
        if kind == KIND_EVENT:
            if not isinstance(body, DomainEvent):
                raise TypeError("an outbox event row needs a DomainEvent body")
        elif kind == KIND_COMMAND:
            if not isinstance(body, Envelope):
                raise TypeError("an outbox command row needs an Envelope body")
            if not capability:
                raise ValueError("an outbox command row needs a capability")
        else:
            raise ValueError(f"unknown outbox kind {kind!r} (expected 'event' or 'command')")
        async with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            self._rows[seq] = OutboxRow(seq=seq, kind=kind, capability=capability, body=body.model_copy(deep=True),
                                        created_at=utcnow())
            return seq

    async def unpublished(self, limit: int = 100) -> Sequence[OutboxRow]:
        async with self._lock:
            rows = sorted((r for r in self._rows.values() if r.published_at is None), key=lambda r: r.seq)[:limit]
            return [dataclasses.replace(r, body=r.body.model_copy(deep=True)) for r in rows]

    async def mark_published(self, seq: int) -> None:
        """Idempotent; the first publication time is kept. Unknown ``seq`` -> ``KeyError``."""
        async with self._lock:
            row = self._rows[seq]
            if row.published_at is None:
                row.published_at = utcnow()

    async def all_rows(self) -> list[OutboxRow]:
        """Every row in ``seq`` order (tests / inspection; not part of the protocol)."""
        async with self._lock:
            return [dataclasses.replace(r) for _, r in sorted(self._rows.items())]


class OutboxPublisher:
    """Drains an ``OutboxStore`` to a ``Bus``. Run ``run_forever`` as a background task, or call ``run_once``."""

    def __init__(self, store: OutboxStore, bus: Bus, *, batch_size: int = 100) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.store = store
        self.bus = bus
        self.batch_size = batch_size
        self._lock = asyncio.Lock()     # one drain at a time per publisher (keeps seq order)
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    async def run_once(self) -> int:
        """Publish every unpublished row in ``seq`` order; return how many were published.

        Each row is marked published right after the bus accepted it. If publishing a row fails, the exception
        propagates: earlier rows stay marked, the failed row and everything after it stay unpublished and are
        retried (in order) on the next run.
        """
        published = 0
        async with self._lock:
            while True:
                rows = await self.store.unpublished(self.batch_size)
                for row in rows:
                    await self._publish(row)
                    await self.store.mark_published(row.seq)
                    published += 1
                if len(rows) < self.batch_size:
                    return published

    async def _publish(self, row: OutboxRow) -> None:
        if row.kind == KIND_EVENT and isinstance(row.body, DomainEvent):
            await self.bus.publish_event(row.body)
        elif row.kind == KIND_COMMAND and isinstance(row.body, Envelope) and row.capability:
            await self.bus.send_command(row.capability, row.body)
        else:
            raise ValueError(f"malformed outbox row seq={row.seq} kind={row.kind!r}")

    async def run_forever(self, interval_s: float = 0.5) -> None:
        """Poll every ``interval_s`` (or sooner after ``notify()``) until ``stop()``. Errors are logged and the
        remaining rows are retried on the next tick. ``stop()`` is sticky: a stopped publisher stays stopped."""
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:
                _log.warning("outbox publish failed; will retry", error=repr(exc))
            self._wake.clear()
            stop_wait = asyncio.ensure_future(self._stop.wait())
            wake_wait = asyncio.ensure_future(self._wake.wait())
            try:
                await asyncio.wait({stop_wait, wake_wait}, timeout=interval_s,
                                   return_when=asyncio.FIRST_COMPLETED)
            finally:
                for fut in (stop_wait, wake_wait):
                    fut.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await fut

    def notify(self) -> None:
        """Hint that new rows were committed: ``run_forever`` drains now instead of at the next tick."""
        self._wake.set()

    def stop(self) -> None:
        """Ask ``run_forever`` to return after the current drain."""
        self._stop.set()

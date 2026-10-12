"""Outbox / inbox store interfaces (research §22, §24). In-memory in Phase A; Postgres in Phase B.

Outbox: the Manager writes events in the SAME transaction as the state change (``UnitOfWork``); a publisher
drains unpublished rows to the bus and marks them published (crash between commit and publish => replayed later).
Inbox: a consumer records ``(consumer_id, message_id)`` in the same transaction as its effect; a duplicate
key means "already processed -> ack and skip".
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from hmap.core.contracts import DomainEvent, Envelope


@dataclass
class OutboxRow:
    seq: int
    kind: str                      # "event" | "command"
    capability: str | None         # for commands
    body: DomainEvent | Envelope
    created_at: datetime
    published_at: datetime | None = None


class OutboxStore(Protocol):
    async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None = None) -> int: ...
    async def unpublished(self, limit: int = 100) -> Sequence[OutboxRow]: ...
    async def mark_published(self, seq: int) -> None: ...


class InboxStore(Protocol):
    async def seen(self, consumer_id: str, message_id: str) -> bool: ...
    async def record(self, consumer_id: str, message_id: str) -> bool:
        """Insert; return False if the pair already existed (duplicate delivery)."""

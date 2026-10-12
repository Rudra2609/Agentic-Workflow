"""Postgres ``OutboxStore`` / ``InboxStore`` (Sprint 1 item 1.8; research §22, §24). Same behaviour as
``InMemoryOutboxStore`` / ``InMemoryInboxStore``; tables from ``alembic/versions/001_sprint_1_core.py``.

Outbox ordering. ``seq`` is an identity column, but identity values are handed out at INSERT time while rows become
visible at COMMIT, so two concurrent writers could commit ``seq`` 5 before 4 and a publisher would publish 5, then 4.
Every outbox insert (here and in ``PostgresTaskStore``) therefore takes the transaction-scoped advisory lock
``OUTBOX_LOCK_KEY`` *immediately before inserting* and holds it until commit: ``seq`` order == commit order, so a
reader always sees a gap-free prefix and ``unpublished()`` can simply read ``ORDER BY seq``. The task store inserts
its staged outbox rows as the last step before COMMIT, so the lock is held only for those inserts + the commit and
no row lock is ever requested while holding it (no deadlocks).

``FOR UPDATE SKIP LOCKED`` is deliberately not used: the protocol reads (``unpublished``) and marks
(``mark_published``) in separate calls, so a row lock would be released before the row is published. One publisher
per database is the supported deployment; a second one only causes duplicates, which the inbox absorbs.

Every event written to the outbox is also appended to ``events`` (append-only audit log) and every command to
``messages``, in the same transaction.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from psycopg.types.json import Jsonb

from hmap.core.bus.stores import OutboxRow
from hmap.core.contracts import DomainEvent, Envelope
from hmap.db.database import Conn, Database
from hmap.db.tables import OUTBOX_LOCK_KEY

KIND_EVENT = "event"
KIND_COMMAND = "command"

OutboxItem = tuple[str, DomainEvent | Envelope, str | None]     # (kind, body, capability)


def validate_outbox_row(kind: str, body: DomainEvent | Envelope, capability: str | None) -> None:
    """The same checks (and exception types) as ``InMemoryOutboxStore.add``."""
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


def _canonical_sha256(doc: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def insert_outbox_rows(conn: Conn, items: Sequence[OutboxItem]) -> list[int]:
    """Append ``items`` to the outbox (+ ``events`` / ``messages`` logs) on ``conn``, which MUST be inside a
    transaction. Takes the outbox advisory lock first (held until that transaction ends). Returns the seqs."""
    if not items:
        return []
    for kind, body, capability in items:
        validate_outbox_row(kind, body, capability)
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (OUTBOX_LOCK_KEY,))
    seqs: list[int] = []
    for kind, body, capability in items:
        doc = body.model_dump(mode="json")
        msg_id: str
        aggregate_id: str | None
        if isinstance(body, DomainEvent):
            msg_id, aggregate_id = body.event_id, body.aggregate_id
            await conn.execute(
                "INSERT INTO events (event_id, event_type, aggregate_id, aggregate_version, project_id,"
                " correlation_id, occurred_at, body) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (event_id) DO NOTHING",
                (body.event_id, body.event_type, body.aggregate_id, body.aggregate_version, body.project_id,
                 body.correlation_id, body.occurred_at, Jsonb(doc)))
        else:
            msg_id, aggregate_id = body.message_id, body.task_id
            await conn.execute(
                "INSERT INTO messages (message_id, message_type, task_id, execution_id, project_id,"
                " correlation_id, sender, receiver, body_sha256, occurred_at, body)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (message_id) DO NOTHING",
                (body.message_id, body.message_type, body.task_id, body.execution_id, body.project_id,
                 body.correlation_id, body.sender.agent_id, body.receiver.agent_id if body.receiver else None,
                 _canonical_sha256(doc), body.occurred_at, Jsonb(doc)))
        cur = await conn.execute(
            "INSERT INTO outbox (kind, capability, message_id, aggregate_id, body)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING seq",
            (kind, capability, msg_id, aggregate_id, Jsonb(doc)))
        row = await cur.fetchone()
        assert row is not None
        seqs.append(int(row["seq"]))
    return seqs


def _row(r: dict[str, Any]) -> OutboxRow:
    body: DomainEvent | Envelope = (DomainEvent.model_validate(r["body"]) if r["kind"] == KIND_EVENT
                                    else Envelope.model_validate(r["body"]))
    return OutboxRow(seq=int(r["seq"]), kind=str(r["kind"]), capability=r["capability"], body=body,
                     created_at=r["created_at"], published_at=r["published_at"])


_ROW_COLUMNS = "seq, kind, capability, body, created_at, published_at"


class PostgresOutboxStore:
    """``OutboxStore`` on the ``outbox`` table. Bodies are stored as JSON, so callers can never mutate a row."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None = None) -> int:
        validate_outbox_row(kind, body, capability)
        async with self.db.transaction() as conn:
            [seq] = await insert_outbox_rows(conn, [(kind, body, capability)])
            return seq

    async def unpublished(self, limit: int = 100) -> Sequence[OutboxRow]:
        if limit <= 0:
            return []
        rows = await self.db.fetch(
            f"SELECT {_ROW_COLUMNS} FROM outbox WHERE published_at IS NULL ORDER BY seq LIMIT %s", (limit,))
        return [_row(r) for r in rows]

    async def mark_published(self, seq: int) -> None:
        """Idempotent; the first publication time is kept. Unknown ``seq`` -> ``KeyError``."""
        rows = await self.db.fetch(
            "UPDATE outbox SET published_at = COALESCE(published_at, clock_timestamp()) WHERE seq = %s RETURNING seq",
            (seq,))
        if not rows:
            raise KeyError(seq)

    async def all_rows(self) -> list[OutboxRow]:
        """Every row in ``seq`` order (tests / inspection; not part of the protocol)."""
        return [_row(r) for r in await self.db.fetch(f"SELECT {_ROW_COLUMNS} FROM outbox ORDER BY seq")]


class PostgresInboxStore:
    """``InboxStore`` on the ``inbox`` table (PK ``(consumer_id, message_id)``). ``record`` is
    ``INSERT ... ON CONFLICT DO NOTHING``: exactly one of several concurrent callers gets ``True``.

    For the research §24 pattern (inbox row in the same transaction as the effect) call :func:`record_inbox` with the
    effect's connection, e.g. ``PostgresTaskStore``'s ``tx.record_inbox(...)``."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def seen(self, consumer_id: str, message_id: str) -> bool:
        rows = await self.db.fetch("SELECT 1 FROM inbox WHERE consumer_id = %s AND message_id = %s",
                                   (consumer_id, message_id))
        return bool(rows)

    async def record(self, consumer_id: str, message_id: str) -> bool:
        async with self.db.connection() as conn:
            return await record_inbox(conn, consumer_id, message_id)

    async def count(self) -> int:
        rows = await self.db.fetch("SELECT count(*) AS n FROM inbox")
        return int(rows[0]["n"])


async def record_inbox(conn: Conn, consumer_id: str, message_id: str) -> bool:
    """Insert the inbox key on ``conn`` (inside the caller's transaction, if any); False if it already existed."""
    cur = await conn.execute(
        "INSERT INTO inbox (consumer_id, message_id) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING 1",
        (consumer_id, message_id))
    return await cur.fetchone() is not None

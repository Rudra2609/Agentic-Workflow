"""Postgres agent registry (Sprint 1 item 1.9; research §16, §19-21) on the ``agents`` table. Same behaviour as
``InMemoryRegistry`` (see its docstring); the clock is injectable so lease tests are deterministic.

- ``register``: upsert; a re-registration bumps ``state_version`` and resets the lease/slots.
- ``heartbeat``: ``SELECT ... FOR UPDATE`` + update in one transaction (concurrent heartbeats do not lose updates).
- ``expire_leases``: one ``UPDATE ... RETURNING``; the returned list is ordered by ``agent_id``.
- ``find_candidates``: capability/lease/state/slot filter in SQL, then the in-memory ordering in Python.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from hmap.core.contracts import (
    SUPPORTED_SCHEMA_VERSIONS,
    AgentHeartbeat,
    AgentRegister,
    AgentState,
    negotiate,
    utcnow,
)
from hmap.core.errors import SchemaUnsupported
from hmap.db.database import Database
from hmap.services.registry.base import AgentRecord
from hmap.services.registry.memory import DEFAULT_LEASE_S, SCHEDULABLE_STATES

_COLUMNS = ("agent_id, plugin, capabilities, protocol_version, state, max_slots, available_slots,"
            " current_execution_ids, lease_until, last_heartbeat, is_stub, state_version")


def _record(row: dict[str, Any]) -> AgentRecord:
    return AgentRecord(**{k: row[k] for k in AgentRecord.model_fields})


class PostgresRegistry:
    def __init__(self, db: Database, *, lease_s: float = DEFAULT_LEASE_S, clock: Callable[[], datetime] = utcnow,
                 supported_versions: tuple[str, ...] = SUPPORTED_SCHEMA_VERSIONS) -> None:
        if lease_s <= 0:
            raise ValueError("lease_s must be positive")
        self.db = db
        self.lease = timedelta(seconds=lease_s)
        self._clock = clock
        self._supported = supported_versions

    # ------------------------------------------------------------------ Registry protocol

    async def register(self, msg: AgentRegister) -> AgentRecord:
        version = negotiate(self._supported, msg.protocol_versions)
        if version is None:
            raise SchemaUnsupported(
                f"agent {msg.agent_id} speaks {msg.protocol_versions}, registry supports {list(self._supported)}")
        now = self._clock()
        rows = await self.db.fetch(
            f"INSERT INTO agents ({_COLUMNS}) VALUES (%(agent_id)s, %(plugin)s, %(caps)s, %(version)s, %(state)s,"
            " %(slots)s, %(slots)s, %(none)s, %(lease)s, %(now)s, %(stub)s, 1)"
            " ON CONFLICT (agent_id) DO UPDATE SET plugin = EXCLUDED.plugin, capabilities = EXCLUDED.capabilities,"
            " protocol_version = EXCLUDED.protocol_version, state = EXCLUDED.state,"
            " max_slots = EXCLUDED.max_slots, available_slots = EXCLUDED.available_slots,"
            " current_execution_ids = EXCLUDED.current_execution_ids, lease_until = EXCLUDED.lease_until,"
            " last_heartbeat = EXCLUDED.last_heartbeat, is_stub = EXCLUDED.is_stub,"
            " state_version = agents.state_version + 1, registered_at = now()"
            f" RETURNING {_COLUMNS}",
            {"agent_id": msg.agent_id, "plugin": msg.plugin, "caps": [c.name for c in msg.capabilities],
             "version": version, "state": AgentState.AVAILABLE.value, "slots": msg.max_slots, "none": [],
             "lease": now + self.lease, "now": now, "stub": msg.is_stub})
        return _record(rows[0])

    async def heartbeat(self, msg: AgentHeartbeat) -> AgentRecord | None:
        async with self.db.transaction() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM agents WHERE agent_id = %s FOR UPDATE", (msg.agent_id,))
            row = await cur.fetchone()
            if row is None:
                return None
            record = _record(row)
            now = self._clock()
            busy = len(msg.current_execution_ids)
            slots = msg.available_slots if msg.available_slots is not None else max(0, record.max_slots - busy)
            cur = await conn.execute(
                "UPDATE agents SET state = %(state)s, available_slots = %(slots)s, current_execution_ids = %(ids)s,"
                " lease_until = %(lease)s, last_heartbeat = %(now)s, state_version = %(sv)s"
                f" WHERE agent_id = %(agent_id)s RETURNING {_COLUMNS}",
                {"state": AgentState(msg.state).value, "slots": min(slots, record.max_slots),
                 "ids": list(msg.current_execution_ids), "lease": now + self.lease, "now": now,
                 "sv": record.state_version + (1 if record.state != msg.state else 0), "agent_id": msg.agent_id})
            updated = await cur.fetchone()
            assert updated is not None
            return _record(updated)

    async def deregister(self, agent_id: str, reason: str) -> None:
        await self.db.fetch("DELETE FROM agents WHERE agent_id = %s RETURNING agent_id", (agent_id,))

    async def find_candidates(self, capability: str) -> list[AgentRecord]:
        rows = await self.db.fetch(
            f"SELECT {_COLUMNS} FROM agents WHERE %s = ANY(capabilities) AND lease_until > %s"
            " AND state = ANY(%s) AND available_slots > 0",
            (capability, self._clock(), sorted(s.value for s in SCHEDULABLE_STATES)))
        found = [_record(r) for r in rows]
        found.sort(key=lambda r: (r.is_stub, 1 - r.available_slots / r.max_slots, r.agent_id))
        return found

    async def expire_leases(self, now: datetime | None = None) -> list[AgentRecord]:
        now = now or self._clock()
        rows = await self.db.fetch(
            "UPDATE agents SET state = %s, available_slots = 0, state_version = state_version + 1"
            f" WHERE state <> %s AND lease_until <= %s RETURNING {_COLUMNS}",
            (AgentState.OFFLINE.value, AgentState.OFFLINE.value, now))
        return sorted((_record(r) for r in rows), key=lambda r: r.agent_id)

    async def list(self) -> list[AgentRecord]:
        return [_record(r) for r in await self.db.fetch(f'SELECT {_COLUMNS} FROM agents ORDER BY agent_id COLLATE "C"')]

    # ------------------------------------------------------------------ extras (not in the protocol)

    async def get(self, agent_id: str) -> AgentRecord | None:
        rows = await self.db.fetch(f"SELECT {_COLUMNS} FROM agents WHERE agent_id = %s", (agent_id,))
        return _record(rows[0]) if rows else None

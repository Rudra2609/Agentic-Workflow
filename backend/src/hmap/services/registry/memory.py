"""In-memory agent registry (Sprint 1 item 1.9; research §16, §19-21).

Advisory projection used for scheduling only; task state stays authoritative in the task store.

- ``register`` negotiates a protocol version (none shared -> ``SchemaUnsupported``) and grants a lease.
- ``heartbeat`` renews the lease and updates state/slots; an unknown agent gets ``None`` (it must re-register).
  An agent marked OFFLINE that heartbeats again is revived (its record is still known).
- ``find_candidates`` = capability match, live lease, AVAILABLE/BUSY with a free slot; real agents before stubs,
  then least loaded, then agent id (deterministic).
- ``expire_leases`` marks agents whose lease ran out OFFLINE and returns them.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from hmap.core.contracts import (
    SUPPORTED_SCHEMA_VERSIONS,
    AgentHeartbeat,
    AgentRegister,
    AgentState,
    negotiate,
    utcnow,
)
from hmap.core.errors import SchemaUnsupported
from hmap.services.registry.base import AgentRecord

DEFAULT_LEASE_S = 30.0
SCHEDULABLE_STATES = frozenset({AgentState.AVAILABLE, AgentState.BUSY})


class InMemoryRegistry:
    def __init__(self, *, lease_s: float = DEFAULT_LEASE_S, clock: Callable[[], datetime] = utcnow,
                 supported_versions: tuple[str, ...] = SUPPORTED_SCHEMA_VERSIONS) -> None:
        if lease_s <= 0:
            raise ValueError("lease_s must be positive")
        self.lease = timedelta(seconds=lease_s)
        self._clock = clock
        self._supported = supported_versions
        self._agents: dict[str, AgentRecord] = {}

    # ------------------------------------------------------------------ Registry protocol

    async def register(self, msg: AgentRegister) -> AgentRecord:
        version = negotiate(self._supported, msg.protocol_versions)
        if version is None:
            raise SchemaUnsupported(
                f"agent {msg.agent_id} speaks {msg.protocol_versions}, registry supports {list(self._supported)}")
        now = self._clock()
        previous = self._agents.get(msg.agent_id)
        record = AgentRecord(
            agent_id=msg.agent_id,
            plugin=msg.plugin,
            capabilities=[c.name for c in msg.capabilities],
            protocol_version=version,
            state=AgentState.AVAILABLE,
            max_slots=msg.max_slots,
            available_slots=msg.max_slots,
            current_execution_ids=[],
            lease_until=now + self.lease,
            last_heartbeat=now,
            is_stub=msg.is_stub,
            state_version=previous.state_version + 1 if previous else 1,
        )
        self._agents[msg.agent_id] = record
        return record.model_copy(deep=True)

    async def heartbeat(self, msg: AgentHeartbeat) -> AgentRecord | None:
        record = self._agents.get(msg.agent_id)
        if record is None:
            return None
        now = self._clock()
        busy = len(msg.current_execution_ids)
        slots = msg.available_slots if msg.available_slots is not None else max(0, record.max_slots - busy)
        updated = record.model_copy(update={
            "state": AgentState(msg.state),
            "available_slots": min(slots, record.max_slots),
            "current_execution_ids": list(msg.current_execution_ids),
            "lease_until": now + self.lease,
            "last_heartbeat": now,
            "state_version": record.state_version + (1 if record.state != msg.state else 0),
        })
        self._agents[msg.agent_id] = updated
        return updated.model_copy(deep=True)

    async def deregister(self, agent_id: str, reason: str) -> None:
        self._agents.pop(agent_id, None)

    async def find_candidates(self, capability: str) -> list[AgentRecord]:
        now = self._clock()
        found = [r for r in self._agents.values()
                 if capability in r.capabilities and r.lease_until > now
                 and r.state in SCHEDULABLE_STATES and r.available_slots > 0]
        found.sort(key=lambda r: (r.is_stub, 1 - r.available_slots / r.max_slots, r.agent_id))
        return [r.model_copy(deep=True) for r in found]

    async def expire_leases(self, now: datetime | None = None) -> list[AgentRecord]:
        now = now or self._clock()
        expired: list[AgentRecord] = []
        for agent_id, r in list(self._agents.items()):
            if r.state != AgentState.OFFLINE and r.lease_until <= now:
                off = r.model_copy(update={"state": AgentState.OFFLINE, "available_slots": 0,
                                           "state_version": r.state_version + 1})
                self._agents[agent_id] = off
                expired.append(off.model_copy(deep=True))
        return expired

    async def list(self) -> list[AgentRecord]:
        return [r.model_copy(deep=True) for r in sorted(self._agents.values(), key=lambda r: r.agent_id)]

    # ------------------------------------------------------------------ extras (not in the protocol)

    async def get(self, agent_id: str) -> AgentRecord | None:
        r = self._agents.get(agent_id)
        return r.model_copy(deep=True) if r else None

"""Agent registry interface (research §19-21, Sprint 1 item 1.9). Manager-owned projection: advisory for
scheduling; task state stays authoritative in the task store."""

from datetime import datetime
from typing import Protocol

from hmap.core.contracts import AgentHeartbeat, AgentRegister, AgentState
from hmap.core.contracts.common import Contract


class AgentRecord(Contract):
    agent_id: str
    plugin: str | None
    capabilities: list[str]
    protocol_version: str
    state: AgentState
    max_slots: int
    available_slots: int
    current_execution_ids: list[str]
    lease_until: datetime
    last_heartbeat: datetime
    is_stub: bool = False
    state_version: int = 0


class Registry(Protocol):
    async def register(self, msg: AgentRegister) -> AgentRecord:
        """Validates protocol versions (SchemaUnsupported if none shared) and creates a lease."""

    async def heartbeat(self, msg: AgentHeartbeat) -> AgentRecord | None:
        """Renews the lease; None if the agent is unknown (it must re-register)."""

    async def deregister(self, agent_id: str, reason: str) -> None: ...

    async def find_candidates(self, capability: str) -> list[AgentRecord]:
        """AVAILABLE/BUSY agents with a live lease and free slots; real agents before stubs, then least loaded."""

    async def expire_leases(self, now: datetime | None = None) -> list[AgentRecord]:
        """Marks agents with expired leases OFFLINE and returns them (manager then reconciles their executions)."""

    async def list(self) -> list[AgentRecord]: ...

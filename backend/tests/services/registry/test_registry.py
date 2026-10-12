from datetime import UTC, datetime, timedelta

import pytest

from hmap.core.contracts import AgentHeartbeat, AgentRegister, AgentState, CapabilityDescriptor
from hmap.core.errors import SchemaUnsupported
from hmap.services.registry.memory import InMemoryRegistry


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, s: float) -> None:
        self.now += timedelta(seconds=s)


def reg(agent_id: str, *caps: str, slots: int = 1, stub: bool = False, versions: tuple[str, ...] = ("1.0",)
        ) -> AgentRegister:
    return AgentRegister(agent_id=agent_id, endpoint="q", capabilities=[CapabilityDescriptor(name=c) for c in caps],
                         protocol_versions=list(versions), max_slots=slots, is_stub=stub)


def hb(clock: Clock, agent_id: str, *, state: AgentState = AgentState.AVAILABLE, slots: int | None = None,
       executions: tuple[str, ...] = ()) -> AgentHeartbeat:
    return AgentHeartbeat(agent_id=agent_id, state=state, observed_at=clock(), available_slots=slots,
                          current_execution_ids=list(executions))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def registry(clock: Clock) -> InMemoryRegistry:
    return InMemoryRegistry(lease_s=30, clock=clock)


async def test_register_negotiates_and_leases(registry: InMemoryRegistry, clock: Clock) -> None:
    rec = await registry.register(reg("a1", "echo", slots=2, versions=("0.9", "1.0", "2.0")))
    assert rec.protocol_version == "1.0"
    assert rec.state == AgentState.AVAILABLE and rec.available_slots == 2
    assert rec.lease_until == clock.now + timedelta(seconds=30)
    assert [r.agent_id for r in await registry.list()] == ["a1"]


async def test_register_without_shared_version_is_rejected(registry: InMemoryRegistry) -> None:
    with pytest.raises(SchemaUnsupported):
        await registry.register(reg("a1", "echo", versions=("2.0",)))
    assert await registry.list() == []


async def test_heartbeat_renews_lease_and_updates_slots(registry: InMemoryRegistry, clock: Clock) -> None:
    await registry.register(reg("a1", "echo", slots=2))
    clock.advance(20)
    rec = await registry.heartbeat(hb(clock, "a1", state=AgentState.BUSY, executions=("E-1",)))
    assert rec is not None
    assert rec.lease_until == clock.now + timedelta(seconds=30)
    assert rec.state == AgentState.BUSY and rec.available_slots == 1 and rec.current_execution_ids == ["E-1"]
    rec = await registry.heartbeat(hb(clock, "a1", slots=0))
    assert rec is not None and rec.available_slots == 0
    assert await registry.heartbeat(hb(clock, "ghost")) is None


async def test_expire_leases_marks_offline(registry: InMemoryRegistry, clock: Clock) -> None:
    await registry.register(reg("a1", "echo"))
    await registry.register(reg("a2", "echo"))
    clock.advance(20)
    await registry.heartbeat(hb(clock, "a2"))
    clock.advance(15)  # a1: 35 s since last renewal, a2: 15 s
    expired = await registry.expire_leases()
    assert [r.agent_id for r in expired] == ["a1"]
    assert expired[0].state == AgentState.OFFLINE
    assert [r.agent_id for r in await registry.find_candidates("echo")] == ["a2"]
    assert await registry.expire_leases() == []          # idempotent
    # a late heartbeat revives the known agent
    rec = await registry.heartbeat(hb(clock, "a1"))
    assert rec is not None and rec.state == AgentState.AVAILABLE
    assert {r.agent_id for r in await registry.find_candidates("echo")} == {"a1", "a2"}


async def test_expire_leases_with_explicit_now(registry: InMemoryRegistry, clock: Clock) -> None:
    await registry.register(reg("a1", "echo"))
    assert await registry.expire_leases(clock.now + timedelta(seconds=29)) == []
    assert len(await registry.expire_leases(clock.now + timedelta(seconds=30))) == 1


async def test_find_candidates_matching_and_ordering(registry: InMemoryRegistry, clock: Clock) -> None:
    await registry.register(reg("stub", "code.implement", slots=4, stub=True))
    await registry.register(reg("busy", "code.implement", slots=2))
    await registry.register(reg("idle", "code.implement", slots=2))
    await registry.register(reg("full", "code.implement", slots=1))
    await registry.register(reg("drain", "code.implement", slots=1))
    await registry.register(reg("other", "test.run", slots=1))
    await registry.heartbeat(hb(clock, "busy", state=AgentState.BUSY, executions=("E-1",)))
    await registry.heartbeat(hb(clock, "full", state=AgentState.BUSY, executions=("E-2",)))
    await registry.heartbeat(hb(clock, "drain", state=AgentState.DRAINING))
    got = [r.agent_id for r in await registry.find_candidates("code.implement")]
    # real before stubs; least loaded first; no free slot / DRAINING / other capability excluded
    assert got == ["idle", "busy", "stub"]
    assert [r.agent_id for r in await registry.find_candidates("test.run")] == ["other"]
    assert await registry.find_candidates("nope") == []


async def test_stub_only_is_still_a_candidate(registry: InMemoryRegistry) -> None:
    await registry.register(reg("stub", "echo", stub=True))
    assert [r.is_stub for r in await registry.find_candidates("echo")] == [True]


async def test_deregister_removes(registry: InMemoryRegistry, clock: Clock) -> None:
    await registry.register(reg("a1", "echo"))
    await registry.deregister("a1", "shutdown")
    assert await registry.find_candidates("echo") == []
    assert await registry.heartbeat(hb(clock, "a1")) is None
    await registry.deregister("a1", "again")  # no error


async def test_reregister_bumps_version(registry: InMemoryRegistry) -> None:
    r1 = await registry.register(reg("a1", "echo"))
    r2 = await registry.register(reg("a1", "echo", "test.run"))
    assert r2.state_version == r1.state_version + 1
    assert r2.capabilities == ["echo", "test.run"]


def test_invalid_lease() -> None:
    with pytest.raises(ValueError):
        InMemoryRegistry(lease_s=0)

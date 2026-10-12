"""Minimal fakes for Manager tests: bus, outbox, artifact/context stores, a controllable clock and scripted agents.
Deliberately independent of the real in-memory bus/outbox (written in parallel by others)."""

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from hmap.core.bus.base import CommandHandler, DeadLetter, EventHandler
from hmap.core.bus.stores import OutboxRow
from hmap.core.contracts import (
    AgentHeartbeat,
    AgentRegister,
    AgentState,
    ArtifactRef,
    CapabilityDescriptor,
    ContextRef,
    Contract,
    DomainEvent,
    Envelope,
    ErrorPayload,
    TaskAck,
    TaskAssign,
    TaskProgress,
    TaskResult,
    TaskStarted,
    make_envelope,
)
from hmap.core.contracts.examples import artifact
from hmap.core.errors import ErrorCode
from hmap.core.plugins import Plugin
from hmap.manager import InMemoryTaskStore, Manager, ManagerConfig
from hmap.services.context.base import ContextSnapshot
from hmap.services.registry.memory import InMemoryRegistry

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


@dataclass
class FakeDelivery:
    body: Envelope | DomainEvent
    attempt: int = 1
    redelivered: bool = False
    outcome: str | None = None          # "ack" | "nack" | "reject"
    reason: str | None = None

    async def ack(self) -> None:
        self.outcome = "ack"

    async def nack(self, *, requeue: bool = True, delay_s: float | None = None) -> None:
        self.outcome = "nack"

    async def reject(self, reason: str) -> None:
        self.outcome, self.reason = "reject", reason


class FakeSubscription:
    def __init__(self) -> None:
        self.cancelled = False

    async def cancel(self) -> None:
        self.cancelled = True


class FakeBus:
    """Commands are kept per capability for the test to pull; replies are queued and delivered on demand."""

    def __init__(self) -> None:
        self.commands: dict[str, list[Envelope]] = {}
        self.events: list[DomainEvent] = []
        self.pending_replies: list[FakeDelivery] = []
        self.deliveries: list[FakeDelivery] = []
        self.reply_handler: CommandHandler | None = None

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def send_command(self, capability: str, envelope: Envelope) -> None:
        self.commands.setdefault(capability, []).append(envelope)

    async def publish_event(self, event: DomainEvent) -> None:
        self.events.append(event)

    async def send_reply(self, envelope: Envelope) -> None:
        self.pending_replies.append(FakeDelivery(envelope))

    async def consume_commands(self, capability: str, handler: CommandHandler, *,
                               prefetch: int = 1) -> FakeSubscription:
        return FakeSubscription()

    async def consume_replies(self, handler: CommandHandler, *, prefetch: int = 16) -> FakeSubscription:
        self.reply_handler = handler
        return FakeSubscription()

    async def subscribe_events(self, pattern: str, handler: EventHandler, *,
                               queue: str | None = None) -> FakeSubscription:
        return FakeSubscription()

    async def dead_letters(self) -> list[DeadLetter]:
        return []

    async def queue_depths(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.commands.items()}

    async def deliver_replies(self) -> int:
        n = 0
        while self.pending_replies:
            d = self.pending_replies.pop(0)
            assert self.reply_handler is not None, "manager not started"
            await self.reply_handler(d)
            self.deliveries.append(d)
            n += 1
        return n

    def take_commands(self, receiver: str) -> list[Envelope]:
        out: list[Envelope] = []
        for cap, envs in self.commands.items():
            mine = [e for e in envs if e.receiver and e.receiver.agent_id == receiver]
            self.commands[cap] = [e for e in envs if e not in mine]
            out.extend(mine)
        return out


class FakeOutbox:
    def __init__(self) -> None:
        self.rows: list[OutboxRow] = []

    async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None = None) -> int:
        seq = len(self.rows) + 1
        self.rows.append(OutboxRow(seq=seq, kind=kind, capability=capability, body=body, created_at=T0))
        return seq

    async def unpublished(self, limit: int = 100) -> Sequence[OutboxRow]:
        return [r for r in self.rows if r.published_at is None][:limit]

    async def mark_published(self, seq: int) -> None:
        self.rows[seq - 1].published_at = T0

    def events(self, event_type: str | None = None, aggregate_id: str | None = None) -> list[DomainEvent]:
        return [r.body for r in self.rows if isinstance(r.body, DomainEvent)
                and (event_type is None or r.body.event_type == event_type)
                and (aggregate_id is None or r.body.aggregate_id == aggregate_id)]


class FakeArtifactStore:
    async def put(self, data: bytes, *, project_id: str, artifact_type: str, media_type: str, created_by: str,
                  artifact_id: str | None = None) -> ArtifactRef:
        return artifact(artifact_id or "ART-X", artifact_type)

    async def get(self, ref: ArtifactRef, *, project_id: str) -> bytes:
        return b"{}"

    async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None:
        return None

    async def list(self, project_id: str) -> list[ArtifactRef]:
        return []

    async def delete_project(self, project_id: str) -> int:
        return 0


class FakeContextStore:
    async def create(self, project_id: str, content: dict[str, Any], *, author: str,
                     context_id: str | None = None, change_summary: str = "") -> ContextRef:
        return ContextRef(context_id=context_id or "CTX-1", version=1)

    async def get(self, ref: ContextRef) -> ContextSnapshot:
        raise KeyError(ref.context_id)

    async def latest(self, context_id: str) -> ContextRef:
        return ContextRef(context_id=context_id, version=1)

    async def is_stale(self, ref: ContextRef) -> bool:
        return False


@dataclass
class Harness:
    clock: FakeClock
    bus: FakeBus
    outbox: FakeOutbox
    store: InMemoryTaskStore
    registry: InMemoryRegistry
    manager: Manager
    agents: list["FakeAgent"] = field(default_factory=list)

    async def pump(self) -> None:
        """Publish the outbox and deliver queued agent replies until quiet."""
        for _ in range(100):
            published = await self.manager.flush_outbox()
            delivered = await self.bus.deliver_replies()
            if not published and not delivered:
                return
        raise AssertionError("pump did not settle")

    async def tick(self, advance_s: float = 0.0) -> None:
        self.clock.advance(advance_s)
        await self.manager.tick()
        await self.pump()

    def agent(self, agent_id: str, *capabilities: str, is_stub: bool = False, max_slots: int = 1) -> "FakeAgent":
        a = FakeAgent(self, agent_id, list(capabilities), is_stub=is_stub, max_slots=max_slots)
        self.agents.append(a)
        return a

    async def task(self, task_id: str) -> dict[str, Any]:
        return await self.manager.get_task(task_id)

    async def state(self, task_id: str) -> str:
        return str((await self.manager.get_task(task_id))["state"])


async def make_harness(*, plugins: Sequence[Plugin] = (), config: ManagerConfig | None = None,
                       lease_s: float = 30.0) -> Harness:
    clock = FakeClock()
    bus = FakeBus()
    outbox = FakeOutbox()
    store = InMemoryTaskStore(outbox)
    registry = InMemoryRegistry(lease_s=lease_s, clock=clock)
    manager = Manager(bus=bus, store=store, outbox=outbox, registry=registry, artifacts=FakeArtifactStore(),
                      contexts=FakeContextStore(), plugins=plugins, clock=clock, config=config,
                      rng=random.Random(42))
    await manager.start()
    return Harness(clock, bus, outbox, store, registry, manager)


class FakeAgent:
    """Scripted agent: the test decides what it replies."""

    def __init__(self, h: Harness, agent_id: str, capabilities: list[str], *, is_stub: bool, max_slots: int) -> None:
        self.h = h
        self.agent_id = agent_id
        self.capabilities = capabilities
        self.is_stub = is_stub
        self.max_slots = max_slots
        self.inbox: list[TaskAssign] = []

    async def _send(self, payload: Contract, **kw: Any) -> None:
        env = make_envelope(payload, sender=self.agent_id, correlation_id=kw.pop("correlation_id", self.agent_id),
                            **kw)
        await self.h.bus.send_reply(env)

    async def register(self, protocol_versions: Sequence[str] = ("1.0",)) -> None:
        await self._send(AgentRegister(
            agent_id=self.agent_id, endpoint=f"hmap.cap.{self.capabilities[0]}",
            capabilities=[CapabilityDescriptor(name=c) for c in self.capabilities],
            protocol_versions=list(protocol_versions), max_slots=self.max_slots, is_stub=self.is_stub))
        await self.h.pump()

    async def heartbeat(self, execution_ids: Sequence[str] = (), state: AgentState = AgentState.AVAILABLE) -> None:
        await self._send(AgentHeartbeat(agent_id=self.agent_id, state=state, observed_at=self.h.clock(),
                                        current_execution_ids=list(execution_ids)))
        await self.h.pump()

    def take(self) -> list[TaskAssign]:
        new = [TaskAssign.model_validate(e.payload) for e in self.h.bus.take_commands(self.agent_id)]
        self.inbox.extend(new)
        return new

    async def ack(self, t: TaskAssign, decision: str = "accepted", reason: str | None = None) -> None:
        await self._send(TaskAck(execution_id=t.execution_id, decision=decision, reason=reason),  # type: ignore[arg-type]
                         task_id=t.task_id)
        await self.h.pump()

    async def started(self, t: TaskAssign) -> None:
        await self._send(TaskStarted(execution_id=t.execution_id), task_id=t.task_id)
        await self.h.pump()

    async def progress(self, t: TaskAssign, percent: int) -> None:
        await self._send(TaskProgress(execution_id=t.execution_id, percent=percent, summary="working"),
                         task_id=t.task_id)
        await self.h.pump()

    async def result(self, t: TaskAssign, outcome: str = "success") -> None:
        ref = artifact(f"ART-{t.task_id[-6:]}-{t.execution_id[-4:]}", t.capability.replace(".", "_"),
                       created_by=self.agent_id)
        await self._send(TaskResult(execution_id=t.execution_id, outcome=outcome,  # type: ignore[arg-type]
                                    artifact_refs=[ref], summary=f"{self.agent_id} done"), task_id=t.task_id)
        await self.h.pump()

    async def error(self, t: TaskAssign, code: ErrorCode, *, retryable: bool | None = None) -> None:
        from hmap.core.errors import is_retryable
        await self._send(ErrorPayload(execution_id=t.execution_id, error_code=code, message=f"{code} happened",
                                      retryable=is_retryable(code) if retryable is None else retryable),
                         task_id=t.task_id)
        await self.h.pump()

    async def complete(self, t: TaskAssign) -> None:
        await self.ack(t)
        await self.started(t)
        await self.progress(t, 50)
        await self.result(t)

    async def work_all(self) -> int:
        """Complete every assignment currently addressed to this agent."""
        n = 0
        for t in self.take():
            await self.complete(t)
            n += 1
        return n


async def run_until_idle(h: Harness, rounds: int = 50) -> None:
    for _ in range(rounds):
        done = 0
        for a in h.agents:
            done += await a.work_all()
        if not done:
            return
    raise AssertionError("agents never went idle")

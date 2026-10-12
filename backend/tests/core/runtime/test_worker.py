"""AgentWorker end-to-end against FakeBus (no real bus, no LLM)."""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from typing import Any

import pytest

from hmap.core.contracts import (
    AgentState,
    ArtifactRef,
    DomainEvent,
    EventType,
    Feedback,
    TaskAssign,
    TaskCancel,
    TaskResult,
    make_envelope,
    utcnow,
)
from hmap.core.errors import ModelTransientError
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.worker import AgentWorker
from hmap.core.tracing import parse_traceparent
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from tests.core.runtime.fakes import DictInbox, FakeBus, FakeLLM, assign_envelope

S = AgentState


class EchoAgent(BaseAgent):
    name = "echo-test"
    capabilities = ("echo",)

    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        self.calls += 1
        await ctx.progress(50, "half way")
        ref = await ctx.put_json({"echo": task.objective}, artifact_type="echo")
        return ctx.result([ref], summary="echoed")


class BlockingAgent(BaseAgent):
    """Runs until released or cancelled (cooperative), checking cancellation every 10 ms."""

    name = "blocking-test"
    capabilities = ("echo",)

    def __init__(self, *, slots: int = 1, honour_cancel: bool = True) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.honour_cancel = honour_cancel
        self.max_slots = slots  # type: ignore[misc]

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        self.started.set()
        while not self.release.is_set():
            if self.honour_cancel:
                ctx.check_cancelled()
            await asyncio.sleep(0.01)
        ref = await ctx.put_json({"done": True}, artifact_type="echo")
        return ctx.result([ref])


class RaisingAgent(BaseAgent):
    name = "raising-test"
    capabilities = ("echo",)

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        raise self.exc


@pytest.fixture
def bus() -> FakeBus:
    return FakeBus()


@pytest.fixture
def inbox() -> DictInbox:
    return DictInbox()


@pytest.fixture
def artifacts() -> InMemoryArtifactStore:
    return InMemoryArtifactStore()


@pytest.fixture
async def make_worker(bus: FakeBus, inbox: DictInbox,
                      artifacts: InMemoryArtifactStore) -> AsyncIterator[Callable[..., AgentWorker]]:
    workers: list[AgentWorker] = []

    def factory(agent: BaseAgent, **kw: Any) -> AgentWorker:
        kw.setdefault("heartbeat_s", 60.0)
        kw.setdefault("drain_timeout_s", 2.0)
        w = AgentWorker(agent, bus, FakeLLM(), artifacts, InMemoryContextStore(), inbox, agent_id="agent-1",
                        plugin="testplug", **kw)
        workers.append(w)
        return w

    yield factory
    for w in workers:  # never leave background tasks behind
        await w.stop("test teardown", timeout_s=0.5)


async def test_register_then_heartbeat_then_consume(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    worker = make_worker(EchoAgent(), heartbeat_s=0.01)
    await worker.start()
    reg = bus.replies[0]
    assert reg.message_type == "agent.register" and reg.sender.agent_id == "agent-1"
    p = reg.payload
    assert p["protocol_versions"] == ["1.0"] and p["max_slots"] == 1 and p["plugin"] == "testplug"
    assert p["is_stub"] is False and [c["name"] for c in p["capabilities"]] == ["echo"]
    assert p["endpoint"] == "hmap.cap.echo"
    assert ("cmd", "echo") in bus.handlers and bus.handlers[("cmd", "echo")][1] == 1  # prefetch = max_slots
    assert ("evt", "task.cancelled") in bus.handlers
    await bus.wait_for(lambda b: len(b.of_type("agent.heartbeat")) >= 3)
    hb = bus.of_type("agent.heartbeat")[0].payload
    assert hb["state"] == "AVAILABLE" and hb["available_slots"] == 1 and hb["current_execution_ids"] == []
    assert worker.state == S.AVAILABLE
    assert [t.dst for t in worker.lifecycle.history] == [S.REGISTERING, S.AVAILABLE]


async def test_task_message_sequence(bus: FakeBus, inbox: DictInbox, artifacts: InMemoryArtifactStore,
                                     make_worker: Callable[..., AgentWorker]) -> None:
    worker = make_worker(EchoAgent())
    await worker.start()
    env = assign_envelope(objective="hello")
    delivery = await bus.deliver("echo", env)
    replies = [e for e in bus.replies if e.execution_id == env.execution_id]
    assert [e.message_type for e in replies] == ["task.ack", "task.started", "task.progress", "task.result"]
    assert replies[0].payload["decision"] == "accepted"
    assert [e.sequence_number for e in replies] == [1, 2, 3, 4]
    assert all(e.correlation_id == env.correlation_id and e.task_id == env.task_id for e in replies)
    assert all(e.receiver is not None and e.receiver.agent_id == "manager" for e in replies)
    parent = parse_traceparent(env.traceparent or "")
    child = parse_traceparent(replies[-1].traceparent or "")
    assert child.trace_id == parent.trace_id and child.span_id != parent.span_id
    assert replies[2].payload == {"execution_id": env.execution_id, "percent": 50, "summary": "half way",
                                  "artifact_refs": []}
    result = TaskResult.model_validate(replies[-1].payload)
    assert result.outcome == "success" and result.summary == "echoed"
    ref = ArtifactRef.model_validate(result.artifact_refs[0])
    assert await artifacts.get(ref, project_id="P-TEST") == b'{\n  "echo": "hello"\n}'
    assert delivery.settled == "ack"
    assert ("agent:echo-test", env.message_id) in inbox.keys
    assert worker.state == S.AVAILABLE and worker.current_execution_ids == []
    busy = [t for t in worker.lifecycle.history if t.dst == S.BUSY]
    assert len(busy) == 1


async def test_duplicate_delivery_processed_once(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = EchoAgent()
    await make_worker(agent).start()
    env = assign_envelope()
    first = await bus.deliver("echo", env)
    second = await bus.deliver("echo", env, redelivered=True)
    assert agent.calls == 1
    assert first.settled == second.settled == "ack"
    assert bus.types(execution_id=env.execution_id).count("task.result") == 1


async def test_concurrent_duplicate_guarded_by_execution_id(bus: FakeBus,
                                                            make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent(slots=2)
    await make_worker(agent).start()
    env = assign_envelope()
    running = asyncio.create_task(bus.deliver("echo", env))
    await agent.started.wait()
    dup = await bus.deliver("echo", env)  # same message while the first copy still runs
    assert dup.settled == "ack"
    agent.release.set()
    first = await running
    assert first.settled == "ack"
    assert bus.types(execution_id=env.execution_id) == ["task.ack", "task.started", "task.result"]


async def test_busy_heartbeat_and_no_slot_rejection(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent(slots=1)
    worker = make_worker(agent)
    await worker.start()
    env1, env2 = assign_envelope(), assign_envelope()
    running = asyncio.create_task(bus.deliver("echo", env1))
    await agent.started.wait()
    assert worker.state == S.BUSY and worker.current_execution_ids == [env1.execution_id]
    await worker._send_heartbeat()
    hb = bus.of_type("agent.heartbeat")[-1].payload
    assert hb["state"] == "BUSY" and hb["available_slots"] == 0 and hb["current_execution_ids"] == [env1.execution_id]
    rejected = await bus.deliver("echo", env2)
    assert rejected.settled == "ack"
    ack = bus.of_type("task.ack")[-1]
    assert ack.execution_id == env2.execution_id
    assert ack.payload["decision"] == "rejected" and ack.payload["reason"] == "no free slot"
    agent.release.set()
    await running
    assert worker.state == S.AVAILABLE


async def test_wrong_capability_rejected(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    await make_worker(EchoAgent()).start()
    env = assign_envelope("research.run")
    delivery = await bus.deliver("echo", env)
    assert delivery.settled == "ack"
    assert bus.types(execution_id=env.execution_id) == ["task.ack"]
    assert bus.replies[-1].payload["decision"] == "rejected"


@pytest.mark.parametrize(("exc", "code", "retryable"), [
    (ModelTransientError("ollama timed out"), "MODEL_TRANSIENT", True),
    (TimeoutError(), "TIMEOUT", True),
    (ValueError("bad input"), "INTERNAL_AGENT", False),
])
async def test_handler_exception_becomes_error_message(bus: FakeBus, inbox: DictInbox,
                                                       make_worker: Callable[..., AgentWorker],
                                                       exc: Exception, code: str, retryable: bool) -> None:
    worker = make_worker(RaisingAgent(exc))
    await worker.start()
    env = assign_envelope()
    delivery = await bus.deliver("echo", env)
    assert bus.types(execution_id=env.execution_id) == ["task.ack", "task.started", "error"]
    err = bus.replies[-1].payload
    assert err["error_code"] == code and err["retryable"] is retryable and err["message"]
    assert delivery.settled == "ack" and len(inbox.keys) == 1
    assert worker.state == S.AVAILABLE


async def test_handler_returning_wrong_type_is_error(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    class Bad(BaseAgent):
        name = "bad"
        capabilities = ("echo",)

        async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
            return "nope"  # type: ignore[return-value]

    await make_worker(Bad()).start()
    await bus.deliver("echo", assign_envelope())
    assert bus.replies[-1].message_type == "error" and bus.replies[-1].payload["error_code"] == "INTERNAL_AGENT"


async def test_deadline_exceeded_is_timeout(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent()
    await make_worker(agent).start()
    env = assign_envelope(deadline=utcnow() + timedelta(milliseconds=50))
    await bus.deliver("echo", env)
    assert bus.replies[-1].payload["error_code"] == "TIMEOUT"


async def test_cancel_event_cancels_running_execution(bus: FakeBus,
                                                      make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent()
    await make_worker(agent).start()
    env = assign_envelope()
    running = asyncio.create_task(bus.deliver("echo", env))
    await agent.started.wait()
    other = await bus.emit(DomainEvent(event_type=EventType.TASK_CANCELLED, aggregate_id="T-other",
                                       data={"execution_id": "E-other"}))
    assert other is not None and other.settled == "ack"
    await asyncio.sleep(0.03)
    assert not running.done()  # a cancel for another execution does not touch ours
    await bus.emit(DomainEvent(event_type=EventType.TASK_CANCELLED, aggregate_id=env.task_id or "",
                               data={"execution_id": env.execution_id, "reason": "human changed the plan"}))
    delivery = await running
    err = bus.replies[-1]
    assert err.message_type == "error" and err.payload["error_code"] == "CANCELLED"
    assert err.payload["retryable"] is False and delivery.settled == "ack"


async def test_cancel_command_by_task_id(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent()
    await make_worker(agent).start()
    env = assign_envelope()
    running = asyncio.create_task(bus.deliver("echo", env))
    await agent.started.wait()
    cancel = make_envelope(TaskCancel(task_id=env.task_id or "", reason="stop"), sender="manager",
                           receiver="cap:echo", correlation_id="c1")
    cancel_delivery = await bus.deliver("echo", cancel)
    assert cancel_delivery.settled == "ack"
    await running
    assert bus.replies[-1].payload["error_code"] == "CANCELLED"


async def test_cancel_before_assignment_arrives(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = EchoAgent()
    await make_worker(agent).start()
    env = assign_envelope()
    await bus.emit(DomainEvent(event_type=EventType.TASK_CANCELLED, aggregate_id=env.task_id or "",
                               data={"execution_id": env.execution_id}))
    delivery = await bus.deliver("echo", env)
    assert agent.calls == 0 and delivery.settled == "ack"
    assert bus.replies[-1].payload["error_code"] == "CANCELLED"


async def test_non_assign_command_rejected(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    await make_worker(EchoAgent()).start()
    env = make_envelope(Feedback(target_execution_id="E-1", decision="approve"), sender="manager",
                        correlation_id="c")
    delivery = await bus.deliver("echo", env)
    assert delivery.settled == "reject"


async def test_reply_failure_nacks_and_does_not_record(bus: FakeBus, inbox: DictInbox,
                                                       make_worker: Callable[..., AgentWorker]) -> None:
    await make_worker(EchoAgent()).start()
    bus.fail_replies = lambda e: e.message_type == "task.result"
    env = assign_envelope()
    delivery = await bus.deliver("echo", env)
    assert delivery.settled == "nack" and not inbox.keys


async def test_progress_failure_is_ignored(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    await make_worker(EchoAgent()).start()
    bus.fail_replies = lambda e: e.message_type == "task.progress"
    delivery = await bus.deliver("echo", assign_envelope())
    assert delivery.settled == "ack" and bus.replies[-1].message_type == "task.result"


async def test_registration_retries_then_succeeds(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    failures = iter([True, True])
    bus.fail_replies = lambda e: e.message_type == "agent.register" and next(failures, False)
    worker = make_worker(EchoAgent(), register_retry_delays_s=(0, 0, 0))
    await worker.start()
    assert worker.state == S.AVAILABLE
    assert [t.dst for t in worker.lifecycle.history] == [
        S.REGISTERING, S.RECOVERING, S.REGISTERING, S.RECOVERING, S.REGISTERING, S.AVAILABLE]


async def test_registration_budget_exhausted_fails(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    bus.fail_replies = lambda e: True
    worker = make_worker(EchoAgent(), register_retry_delays_s=(0,))
    with pytest.raises(ConnectionError):
        await worker.start()
    assert worker.state == S.FAILED and not bus.handlers
    await worker.stop()
    assert worker.state == S.OFFLINE


async def test_stop_deregisters(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    worker = make_worker(EchoAgent(), heartbeat_s=0.01)
    await worker.start()
    await worker.stop("shutdown")
    assert bus.replies[-1].message_type == "agent.deregister"
    assert bus.replies[-1].payload == {"agent_id": "agent-1", "reason": "shutdown"}
    assert bus.of_type("agent.heartbeat")[-1].payload["state"] == "DRAINING"
    assert worker.state == S.OFFLINE and not bus.handlers
    assert worker._heartbeat_task is not None and worker._heartbeat_task.done()
    count = len(bus.replies)
    await asyncio.sleep(0.03)
    assert len(bus.replies) == count  # heartbeat loop really stopped
    await worker.stop()  # idempotent


async def test_stop_waits_for_in_flight_work(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent()
    worker = make_worker(agent)
    await worker.start()
    env = assign_envelope()
    running = asyncio.create_task(bus.deliver("echo", env))
    await agent.started.wait()
    stopping = asyncio.create_task(worker.stop())
    await asyncio.sleep(0.02)
    assert worker.state == S.DRAINING and not stopping.done()
    late = await bus.deliver("echo", assign_envelope())  # draining: left unsettled for redelivery elsewhere
    assert late.settled is None
    agent.release.set()
    await stopping
    delivery = await running
    assert delivery.settled == "ack"
    types = bus.types()
    assert types.index("task.result") < types.index("agent.deregister")
    assert worker.state == S.OFFLINE


async def test_stop_deadline_cancels_cooperatively(bus: FakeBus, make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent()
    worker = make_worker(agent)
    await worker.start()
    running = asyncio.create_task(bus.deliver("echo", assign_envelope()))
    await agent.started.wait()
    await worker.stop(timeout_s=0.02)
    delivery = await running
    err = bus.of_type("error")[-1].payload
    assert err["error_code"] == "AGENT_UNAVAILABLE" and err["retryable"] is True
    assert delivery.settled == "ack" and bus.replies[-1].message_type == "agent.deregister"


async def test_stop_hard_cancels_uncooperative_handler(bus: FakeBus,
                                                       make_worker: Callable[..., AgentWorker]) -> None:
    agent = BlockingAgent(honour_cancel=False)
    worker = make_worker(agent, cancel_grace_s=0.02)
    await worker.start()
    running = asyncio.create_task(bus.deliver("echo", assign_envelope()))
    await agent.started.wait()
    await worker.stop(timeout_s=0.02)
    delivery = await running
    assert delivery.settled is None  # unsettled -> the broker redelivers it when the consumer goes away
    assert "task.result" not in bus.types() and "error" not in bus.types()
    assert bus.replies[-1].message_type == "agent.deregister" and worker.state == S.OFFLINE


async def test_on_start_failure_marks_failed(make_worker: Callable[..., AgentWorker]) -> None:
    class Broken(EchoAgent):
        async def on_start(self) -> None:
            raise RuntimeError("model missing")

    worker = make_worker(Broken())
    with pytest.raises(RuntimeError):
        await worker.start()
    assert worker.state == S.FAILED


def test_constructor_validation(bus: FakeBus) -> None:
    deps: tuple[Any, ...] = (bus, FakeLLM(), InMemoryArtifactStore(), InMemoryContextStore(), DictInbox())
    with pytest.raises(ValueError):
        AgentWorker(EchoAgent(), *deps, capabilities=["research.run"])
    w = AgentWorker(EchoAgent(), *deps)
    assert w.agent_id.startswith("echo-test-") and w.capabilities == ("echo",)


class _GatewayLike(FakeLLM):
    """Stands in for the gateway: ``local_only()`` hands out a never-cloud copy."""

    def __init__(self, local: bool = False) -> None:
        self.local = local

    def local_only(self) -> "_GatewayLike":
        return _GatewayLike(local=True)


class LLMSpyAgent(BaseAgent):
    name = "llm-spy"
    capabilities = ("echo",)

    def __init__(self) -> None:
        self.seen: list[Any] = []

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        self.seen.append(ctx.llm)
        ref = await ctx.put_json({"ok": True}, artifact_type="echo")
        return ctx.result([ref])


async def test_a_local_only_project_task_gets_a_never_cloud_llm(bus: FakeBus, inbox: DictInbox,
                                                               artifacts: InMemoryArtifactStore) -> None:
    llm, agent = _GatewayLike(), LLMSpyAgent()
    worker = AgentWorker(agent, bus, llm, artifacts, InMemoryContextStore(), inbox, agent_id="agent-1",
                         plugin="testplug", heartbeat_s=60.0, drain_timeout_s=2.0)
    await worker.start()
    try:
        await bus.deliver("echo", assign_envelope(objective="private", cloud_ok=False))
        await bus.deliver("echo", assign_envelope(objective="shared"))
        assert [x.local for x in agent.seen] == [True, False]
        assert agent.seen[1] is llm and llm.local is False       # the shared client is never changed
    finally:
        await worker.stop("test teardown", timeout_s=0.5)

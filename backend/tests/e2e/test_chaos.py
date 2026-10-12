"""Failure scenarios (Sprint 1 item 1.19) on the in-memory platform.

Covered here: agent crash mid-task, duplicate message, retry -> dead letter, manager restart with outbox replay,
out-of-order (late) message. Result-after-timeout is covered by tests/manager. Broker restart needs the real
RabbitMQ adapter and is added in Phase B (tests marked ``integration``).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import pytest

from hmap.core.contracts import (
    ProjectState,
    TaskAssign,
    TaskResult,
    TaskStarted,
    TaskState,
    make_envelope,
)
from hmap.core.contracts.domain import PlanTask, TaskGraph
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.discovery import discover
from hmap.core.runtime.worker import AgentWorker
from hmap.manager.config import ManagerConfig
from hmap.manager.manager import Manager
from hmap.system import HmapSystem, SystemConfig

FAST = SystemConfig(lease_s=0.6, heartbeat_s=0.1, watchdog_interval_s=0.05,
                    manager=ManagerConfig(ack_timeout_s=2, retry_delays_s=(0.05, 0.05, 0.05), retry_jitter=0.0,
                                          max_retries=2, offline_grace_s=0.2))


async def wait_for(cond: Callable[[], Awaitable[bool]], timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not await cond():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def graph(pid: str, *tasks: tuple[str, str, list[str], dict[str, Any]]) -> TaskGraph:
    return TaskGraph(project_id=pid, tasks=[
        PlanTask(id=tid, title=tid, agent_capability=cap, depends_on=deps) for tid, cap, deps, _ in tasks])


async def project_state(m: Manager, pid: str) -> str:
    return str((await m.get_project(pid))["state"])


class FlakyAgent(BaseAgent):
    """Always fails with a retryable error."""

    name = "flaky"
    capabilities: ClassVar[tuple[str, ...]] = ("flaky.op",)
    calls = 0

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        type(self).calls += 1
        raise HmapError("tool timed out", code=ErrorCode.TOOL_TRANSIENT)


@pytest.fixture
async def make_system(tmp_path):
    systems: list[HmapSystem] = []

    async def _make(plugins: list[Plugin] | None = None, *, agents: bool = True) -> HmapSystem:
        s = HmapSystem.in_memory(artifact_root=tmp_path / f"a{len(systems)}", plugins=plugins, config=FAST)
        await s.start(with_agents=agents)
        systems.append(s)
        return s

    yield _make
    for s in systems:
        for host in getattr(s, "extra_hosts", []):
            await host.stop()
        await s.stop()


def crash(worker: AgentWorker) -> asyncio.Task[None]:
    """Kill a worker without deregistering: heartbeats stop, its unacked deliveries go back to the queue."""
    assert worker._heartbeat_task is not None
    worker._heartbeat_task.cancel()
    return asyncio.ensure_future(worker._cancel_subscriptions())


async def test_agent_crash_mid_task_recovers_on_another_agent(make_system) -> None:
    s = await make_system()
    first = s.host
    assert first is not None
    second = await s.start_agents()          # a second set of stub agents = a spare research agent
    s.extra_hosts = [first]  # type: ignore[attr-defined]  # both hosts are stopped at teardown
    m = s.manager
    pid = await m.create_project("crash")
    g = graph(pid, ("T1", "research.run", [], {}))
    g.tasks[0].description = "slow"
    await m.submit_graph(pid, g, require_approval=True)
    # while the plan waits for approval, make the research task slow so we can kill whoever picks it up
    [task] = await m.list_tasks(pid)
    async with m.store.transaction() as tx:
        rec = await tx_get(m, task["task_id"])
        rec.inputs = {**rec.inputs, "stub_delay_s": 1.0}
        await tx.update_task(rec, expected_version=rec.state_version)
    await m.approve(pid, True)

    async def running_worker() -> AgentWorker | None:
        for w in [*first.workers, *second.workers]:
            if w.current_execution_ids:
                return w
        return None

    async def someone_running() -> bool:
        return await running_worker() is not None

    await wait_for(someone_running)
    victim = await running_worker()
    assert victim is not None
    await crash(victim)

    async def completed() -> bool:
        return await project_state(m, pid) == ProjectState.COMPLETED

    await wait_for(completed)

    async def victim_offline() -> bool:
        rec = await s.registry.list()
        return any(a.agent_id == victim.agent_id and a.state == "OFFLINE" for a in rec)

    await wait_for(victim_offline)


async def tx_get(m: Manager, task_id: str):  # helper: fetch a mutable task record
    return await m.store.get_task(task_id)


async def test_duplicate_assignment_is_processed_once(make_system) -> None:
    s = await make_system()
    m = s.manager
    results: list[str] = []
    original = s.bus.send_reply

    async def spy(env):  # count task.result replies leaving the agents
        if env.message_type == "task.result":
            results.append(env.execution_id or "")
        await original(env)

    s.bus.send_reply = spy  # type: ignore[method-assign]
    pid = await m.create_project("dup")
    await m.submit_graph(pid, graph(pid, ("T1", "echo", [], {})), require_approval=False)

    async def completed() -> bool:
        return await project_state(m, pid) == ProjectState.COMPLETED

    await wait_for(completed)
    assign_rows = [r for r in await s.outbox.all_rows() if r.kind == "command"]
    assert len(assign_rows) == 1
    await s.bus.send_command("echo", assign_rows[0].body)      # broker redelivers the same message
    await asyncio.sleep(0.4)
    assert len(results) == 1                                    # inbox dedup: handler not run twice


async def test_retries_exhausted_dead_letters_and_blocks_dependants(make_system) -> None:
    FlakyAgent.calls = 0
    plugins = [*discover(), Plugin(name="flaky", agents=[FlakyAgent], priority=100)]
    s = await make_system(plugins)
    m = s.manager
    pid = await m.create_project("dlq")
    await m.submit_graph(pid, graph(pid, ("T1", "flaky.op", [], {}), ("T2", "echo", ["T1"], {})),
                         require_approval=False)

    async def settled() -> bool:
        states = {t["plan_task_id"]: t["state"] for t in await m.list_tasks(pid)}
        return states.get("T1") == TaskState.DEAD_LETTERED and states.get("T2") == TaskState.BLOCKED

    await wait_for(settled)
    assert FlakyAgent.calls == 1 + FAST.manager.max_retries          # first try + retries, each a new execution
    t1 = next(t for t in await m.list_tasks(pid) if t["plan_task_id"] == "T1")
    executions = (await m.get_task(t1["task_id"]))["executions"]
    assert len({e["execution_id"] for e in executions}) == FlakyAgent.calls
    assert await project_state(m, pid) == ProjectState.FAILED


async def test_manager_restart_replays_outbox(make_system) -> None:
    s = await make_system()
    s.publisher.stop()                                   # simulate: crash after commit, before publish
    assert s._publisher_task is not None
    s._publisher_task.cancel()
    m = s.manager
    pid = await m.create_project("restart")
    await m.submit_graph(pid, graph(pid, ("T1", "echo", [], {}), ("T2", "echo", ["T1"], {})),
                         require_approval=False)
    assert await s.outbox.unpublished()                  # the assign command is committed but not sent
    await m.stop()

    # "restart": a new Manager over the same durable store/outbox/registry
    m2 = Manager(bus=s.bus, store=s.store, outbox=s.outbox, registry=s.registry, artifacts=s.artifacts,
                 contexts=s.contexts, plugins=s.plugins, config=FAST.manager)
    await m2.start(watchdog_interval_s=0.05)
    s.manager = m2
    from hmap.core.bus.outbox import OutboxPublisher
    s.publisher = OutboxPublisher(s.outbox, s.bus)
    s._publisher_task = asyncio.create_task(s.publisher.run_forever(0.05))

    async def completed() -> bool:
        return await project_state(m2, pid) == ProjectState.COMPLETED

    await wait_for(completed)


async def test_late_started_after_completed_does_not_regress(make_system) -> None:
    s = await make_system()
    m = s.manager
    pid = await m.create_project("late")
    await m.submit_graph(pid, graph(pid, ("T1", "echo", [], {})), require_approval=False)

    async def completed() -> bool:
        return await project_state(m, pid) == ProjectState.COMPLETED

    await wait_for(completed)
    [task] = await m.list_tasks(pid)
    detail = await m.get_task(task["task_id"])
    exe = detail["executions"][-1]
    late = make_envelope(TaskStarted(execution_id=exe["execution_id"]), sender=exe["agent_id"] or "x",
                         correlation_id=pid, task_id=task["task_id"])
    await s.bus.send_reply(late)
    await asyncio.sleep(0.3)
    assert (await m.list_tasks(pid))[0]["state"] == TaskState.COMPLETED

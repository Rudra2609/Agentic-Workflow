"""Manager behaviour end to end over fakes: graph execution, approval gate, retries, DLQ, timeouts, cancellation,
hooks. Agents are scripted; the bus/outbox are fakes; time is a FakeClock."""

from typing import Any

import pytest

from hmap.core.contracts import (
    DomainEvent,
    EventType,
    ExecutionStatus,
    PlanTask,
    ProjectState,
    TaskGraph,
    TaskStarted,
    TaskState,
    make_envelope,
)
from hmap.core.contracts.examples import TASK_GRAPH
from hmap.core.errors import ErrorCode
from hmap.core.plugins import ManagerHandle, Plugin, hook
from hmap.manager import InvalidProjectState, ManagerConfig, NaiveTopologicalExecutor, UnknownProject
from hmap.manager.records import TaskRecord
from tests.manager.fakes import FakeDelivery, Harness, make_harness, run_until_idle

S = TaskState

SIX_TASKS = TaskGraph(project_id="P-plan", tasks=[
    PlanTask(id="A", title="Extract requirements", agent_capability="document.extract"),
    PlanTask(id="B", title="Research", agent_capability="research.run", depends_on=["A"]),
    PlanTask(id="C", title="Implement", agent_capability="code.implement", depends_on=["A"]),
    PlanTask(id="D", title="Verify claims", agent_capability="verify.claims", depends_on=["B"]),
    PlanTask(id="E", title="Test", agent_capability="test.run", depends_on=["C"]),
    PlanTask(id="F", title="Final review", agent_capability="review.final", depends_on=["D", "E"]),
])
CAPS = sorted({t.agent_capability for t in SIX_TASKS.tasks})


async def project_with_graph(h: Harness, graph: TaskGraph = SIX_TASKS, *, approve: bool = True,
                             require_approval: bool = True) -> tuple[str, dict[str, str]]:
    pid = await h.manager.create_project("demo")
    await h.manager.submit_graph(pid, graph, require_approval=require_approval)
    if require_approval and approve:
        await h.manager.approve(pid, True, "ok")
    await h.pump()
    project = await h.manager.get_project(pid)
    return pid, project["plan_task_map"]


async def single_task(h: Harness, capability: str = "echo", **kw: Any) -> str:
    pid = await h.manager.create_project("one")
    tid = await h.manager.create_task(pid, capability, "do it", **kw)
    await h.pump()
    return tid


# ============================================================================================ graph + approval


async def test_six_task_graph_runs_to_completion_through_the_approval_gate() -> None:
    h = await make_harness()
    agents = {cap: h.agent(f"agent-{cap}", cap) for cap in CAPS}
    for a in agents.values():
        await a.register()

    pid = await h.manager.create_project("demo")
    await h.manager.submit_graph(pid, SIX_TASKS)
    await h.pump()
    project = await h.manager.get_project(pid)
    m = project["plan_task_map"]
    assert project["state"] == ProjectState.AWAITING_APPROVAL
    assert project["approvals"][0]["status"] == "pending"
    assert set(m) == set("ABCDEF") and all(v.startswith("T-") for v in m.values())
    # gate: nothing is ready or assigned before approval, even after a tick
    await h.tick(1)
    assert {await h.state(t) for t in m.values()} == {S.CREATED}
    assert all(not cmds for cmds in h.bus.commands.values())

    await h.manager.approve(pid, True, "looks good")
    await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.EXECUTING
    assert await h.state(m["A"]) == S.ASSIGNED
    assert await h.state(m["B"]) == S.CREATED

    # dependencies are mapped to real task ids
    task_c = await h.task(m["C"])
    assert task_c["depends_on"] == [m["A"]] and task_c["plan_task_id"] == "C"

    # A completes -> B and C become ready and are BOTH assigned (parallel)
    assert await agents["document.extract"].work_all() == 1
    assert await h.state(m["B"]) == S.ASSIGNED
    assert await h.state(m["C"]) == S.ASSIGNED
    b_assign = agents["research.run"].take()[0]
    c_assign = agents["code.implement"].take()[0]
    # the dependant receives the upstream result artifacts
    a_refs = (await h.task(m["A"]))["executions"][0]["result_refs"]
    assert [r.artifact_id for r in b_assign.artifact_refs] == [a_refs[0]["artifact_id"]]
    assert b_assign.inputs["dependency_artifacts"] == {m["A"]: [a_refs[0]["artifact_id"]]}
    assert b_assign.inputs["plan_task_id"] == "B"
    await agents["research.run"].complete(b_assign)
    await agents["code.implement"].complete(c_assign)

    await run_until_idle(h)
    for plan_id, tid in m.items():
        assert await h.state(tid) == S.COMPLETED, plan_id
    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.COMPLETED
    assert project["approvals"][0]["status"] == "approved"
    assert h.outbox.events(EventType.PROJECT_COMPLETED.value, pid)
    # every delivery was processed and acked
    assert h.bus.deliveries and {d.outcome for d in h.bus.deliveries} == {"ack"}
    # every event published to the bus
    assert len(h.bus.events) == len(h.outbox.events())


async def test_task_events_follow_state_versions() -> None:
    h = await make_harness()
    a = h.agent("echo-1", "echo")
    await a.register()
    tid = await single_task(h)
    await a.work_all()
    events = h.outbox.events(aggregate_id=tid)
    types = [e.event_type for e in events]
    assert types == ["task.created", "task.ready", "task.assigned", "task.accepted", "task.started",
                     "task.progress", "task.result_submitted", "task.completed"]
    state_events = [e for e in events if e.event_type != "task.progress"]
    assert [e.aggregate_version for e in state_events] == list(range(1, len(state_events) + 1))
    final = await h.task(tid)
    assert final["state_version"] == state_events[-1].aggregate_version
    assert all(e.data["capability"] == "echo" for e in events)


async def test_approval_rejected_cancels_graph_and_returns_to_planning() -> None:
    h = await make_harness()
    pid, m = await project_with_graph(h, approve=False)
    await h.manager.approve(pid, False, "too vague")
    await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.PLANNING
    assert {await h.state(t) for t in m.values()} == {S.CANCELLED}
    with pytest.raises(InvalidProjectState):
        await h.manager.approve(pid, True)


async def test_graph_without_approval_starts_immediately_and_waits_for_agents() -> None:
    h = await make_harness()
    pid, m = await project_with_graph(h, TASK_GRAPH, require_approval=False)
    assert (await h.manager.get_project(pid))["state"] == ProjectState.EXECUTING
    assert await h.state(m["T1"]) == S.READY          # no agent yet: stays READY
    await h.tick(10)
    assert await h.state(m["T1"]) == S.READY
    agent = h.agent("r", "research.run")
    await agent.register()                            # registration triggers assignment
    assert await h.state(m["T1"]) == S.ASSIGNED


async def test_unknown_project() -> None:
    h = await make_harness()
    with pytest.raises(UnknownProject):
        await h.manager.create_task("P-nope", "echo", "x")
    with pytest.raises(UnknownProject):
        await h.manager.submit_graph("P-nope", SIX_TASKS)


# ============================================================================================ assignment


async def test_real_agent_preferred_over_stub_and_slots_respected() -> None:
    h = await make_harness()
    stub = h.agent("stub-echo", "echo", is_stub=True)
    real = h.agent("real-echo", "echo")
    await stub.register()
    await real.register()
    pid = await h.manager.create_project("p")
    t1 = await h.manager.create_task(pid, "echo", "one")
    t2 = await h.manager.create_task(pid, "echo", "two")
    t3 = await h.manager.create_task(pid, "echo", "three")
    await h.pump()
    assert [a.task_id for a in real.take()] == [t1]   # real first, 1 slot
    assert [a.task_id for a in stub.take()] == [t2]   # stub has the only other slot
    assert await h.state(t3) == S.READY               # no capacity left (before any heartbeat)


async def test_rejected_ack_reassigns_to_another_agent() -> None:
    h = await make_harness()
    a1 = h.agent("a1", "echo")
    a2 = h.agent("a2", "echo")
    await a1.register()
    tid = await single_task(h)
    first = a1.take()[0]
    await a2.register()
    await a1.ack(first, "rejected", "capacity")
    second = a2.take()
    assert len(second) == 1 and second[0].execution_id != first.execution_id
    t = await h.task(tid)
    assert t["state"] == S.ASSIGNED and t["rejected_by"] == ["a1"] and t["retries"] == 0
    old = next(e for e in t["executions"] if e["execution_id"] == first.execution_id)
    assert old["status"] == ExecutionStatus.SUPERSEDED and old["superseded_by"] == second[0].execution_id


async def test_out_of_order_started_before_ack() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.started(t)
    assert await h.state(tid) == S.RUNNING
    await a.ack(t)                                     # late ack: evidence only
    task = await h.task(tid)
    assert task["state"] == S.RUNNING
    assert task["executions"][0]["evidence"][0]["message_type"] == "task.ack"
    await a.result(t)
    assert await h.state(tid) == S.COMPLETED
    await a.started(t)                                 # late started after COMPLETED: recorded, no regression
    task = await h.task(tid)
    assert task["state"] == S.COMPLETED
    assert [e["message_type"] for e in task["executions"][0]["evidence"]] == ["task.ack", "task.started"]


# ============================================================================================ retries / DLQ


async def test_retryable_error_retries_with_new_execution_then_succeeds() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    first = a.take()[0]
    await a.ack(first)
    await a.started(first)
    await a.error(first, ErrorCode.MODEL_TRANSIENT)
    t = await h.task(tid)
    assert t["state"] == S.RETRY_SCHEDULED and t["retries"] == 1 and t["active_execution_id"] is None
    assert t["executions"][0]["status"] == ExecutionStatus.FAILED
    retrying = h.outbox.events(EventType.TASK_RETRYING.value, tid)[0]
    assert 5.0 <= retrying.data["delay_s"] <= 5.5     # first step 5 s + bounded jitter (10 %)

    await h.tick(4.9)                                  # backoff not elapsed
    assert await h.state(tid) == S.RETRY_SCHEDULED
    assert a.take() == []
    await h.tick(0.7)
    second = a.take()
    assert len(second) == 1 and second[0].execution_id != first.execution_id
    t = await h.task(tid)
    assert t["state"] == S.ASSIGNED and t["attempts"] == 2
    old, new = t["executions"]
    assert old["status"] == ExecutionStatus.SUPERSEDED and old["superseded_by"] == new["execution_id"]
    assert old["error"]["code"] == ErrorCode.MODEL_TRANSIENT
    assert (new["attempt"], new["status"]) == (2, ExecutionStatus.PENDING)

    await a.complete(second[0])
    assert await h.state(tid) == S.COMPLETED


async def test_retry_budget_exhausted_dead_letters_and_blocks_dependants() -> None:
    h = await make_harness(lease_s=10_000)          # the agent stays live across long backoffs
    a = h.agent("a", "echo")
    await a.register()
    pid = await h.manager.create_project("p")
    tid = await h.manager.create_task(pid, "echo", "flaky")
    child = await h.manager.create_task(pid, "echo", "needs flaky", depends_on=[tid])
    grandchild = await h.manager.create_task(pid, "echo", "needs child", depends_on=[child])
    await h.pump()
    execution_ids = []
    for attempt in range(4):                         # first try + 3 retries
        assign = a.take()
        assert len(assign) == 1, attempt
        execution_ids.append(assign[0].execution_id)
        await a.ack(assign[0])
        await a.error(assign[0], ErrorCode.NETWORK)
        await h.tick(200)                            # past any backoff step
    t = await h.task(tid)
    assert t["state"] == S.DEAD_LETTERED and t["attempts"] == 4 and t["retries"] == 3
    assert len(set(execution_ids)) == 4
    assert t["executions"][-1]["status"] == ExecutionStatus.DEAD_LETTERED
    dl = h.outbox.events(EventType.TASK_DEAD_LETTERED.value, tid)
    assert len(dl) == 1 and len(dl[0].data["history"]) == 4 and dl[0].data["needs_review"] is True
    assert await h.state(child) == S.BLOCKED
    assert await h.state(grandchild) == S.BLOCKED
    assert a.take() == []


async def test_backoff_steps_grow() -> None:
    h = await make_harness(config=ManagerConfig(retry_jitter=0.0), lease_s=10_000)
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    for _ in range(3):
        t = a.take()[0]
        await a.error(t, ErrorCode.TOOL_TRANSIENT)
        await h.tick(121)
    delays = [e.data["delay_s"] for e in h.outbox.events(EventType.TASK_RETRYING.value, tid)]
    assert delays == [5.0, 30.0, 120.0]


async def test_non_retryable_error_fails_and_blocks_dependants() -> None:
    h = await make_harness()
    agents = {cap: h.agent(f"agent-{cap}", cap) for cap in CAPS}
    for a in agents.values():
        await a.register()
    pid, m = await project_with_graph(h)
    await agents["document.extract"].work_all()
    research = agents["research.run"].take()[0]
    await agents["research.run"].ack(research)
    await agents["research.run"].error(research, ErrorCode.INVALID_TASK)
    assert await h.state(m["B"]) == S.FAILED
    assert await h.state(m["D"]) == S.BLOCKED         # direct dependant
    await run_until_idle(h)                           # C and E still run
    assert await h.state(m["C"]) == S.COMPLETED
    assert await h.state(m["E"]) == S.COMPLETED
    assert await h.state(m["F"]) == S.BLOCKED         # depends on blocked D
    blocked_f = await h.task(m["F"])
    assert blocked_f["blocked_by"] == [m["D"]]
    assert (await h.manager.get_project(pid))["state"] == ProjectState.FAILED
    assert h.outbox.events("project.failed", pid)


async def test_agent_cannot_make_a_never_retry_code_retryable() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.error(t, ErrorCode.AUTHORIZATION, retryable=True)
    assert await h.state(tid) == S.FAILED


async def test_missing_context_blocks() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.error(t, ErrorCode.MISSING_CONTEXT)
    task = await h.task(tid)
    assert task["state"] == S.BLOCKED and task["blocked_by"] == [ErrorCode.MISSING_CONTEXT]


async def test_failure_outcome_fails_task_but_keeps_result_refs() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.result(t, outcome="failure")
    task = await h.task(tid)
    assert task["state"] == S.FAILED and task["last_error"]["code"] == ErrorCode.WRONG_RESULT
    assert task["executions"][0]["result_refs"]


# ============================================================================================ timeouts / offline


async def test_result_after_ack_timeout_is_kept_as_evidence_only() -> None:
    h = await make_harness()
    slow = h.agent("slow", "echo")
    await slow.register()
    tid = await single_task(h)
    e1 = slow.take()[0]
    await h.tick(31)                                  # no ack within 30 s
    t = await h.task(tid)
    assert t["state"] == S.RETRY_SCHEDULED
    assert t["executions"][0]["status"] == ExecutionStatus.TIMED_OUT
    assert t["last_error"]["code"] == ErrorCode.TIMEOUT

    await slow.result(e1)                             # late result for the timed-out execution
    t = await h.task(tid)
    assert t["state"] == S.RETRY_SCHEDULED            # unchanged
    assert t["executions"][0]["evidence"][0]["message_type"] == "task.result"
    assert t["executions"][0]["result_refs"] == []

    await slow.heartbeat()                            # keep the agent's lease alive
    await h.tick(6)
    e2 = slow.take()[0]
    assert e2.execution_id != e1.execution_id
    await slow.result(e1)                             # still ignored while E2 is active
    assert await h.state(tid) == S.ASSIGNED
    await slow.complete(e2)
    t = await h.task(tid)
    assert t["state"] == S.COMPLETED
    assert t["executions"][0]["status"] == ExecutionStatus.SUPERSEDED
    assert t["executions"][1]["status"] == ExecutionStatus.SUCCEEDED
    assert {d.outcome for d in h.bus.deliveries} == {"ack"}


async def test_offline_agent_work_is_retried_only_after_grace() -> None:
    h = await make_harness(config=ManagerConfig(offline_grace_s=15, retry_jitter=0.0))
    dying = h.agent("dying", "echo")
    await dying.register()
    tid = await single_task(h)
    t = dying.take()[0]
    await dying.ack(t)
    await dying.started(t)
    await h.tick(31)                                  # lease (30 s) expired -> OFFLINE, grace starts
    assert h.outbox.events(EventType.AGENT_OFFLINE.value, "dying")
    task = await h.task(tid)
    assert task["state"] == S.RUNNING and task["executions"][0]["orphaned_at"] is not None
    await h.tick(10)                                  # still within grace
    assert await h.state(tid) == S.RUNNING
    await h.tick(6)                                   # grace over -> retry scheduled
    task = await h.task(tid)
    assert task["state"] == S.RETRY_SCHEDULED
    assert task["executions"][0]["status"] == ExecutionStatus.TIMED_OUT
    assert task["last_error"]["code"] == ErrorCode.AGENT_UNAVAILABLE
    fresh = h.agent("fresh", "echo")
    await fresh.register()
    await h.tick(5)
    assert len(fresh.take()) == 1


async def test_agent_back_within_grace_keeps_its_execution() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.ack(t)
    await a.started(t)
    await h.tick(31)
    assert (await h.task(tid))["executions"][0]["orphaned_at"] is not None
    await a.heartbeat([t.execution_id])               # late heartbeat, lists the execution
    assert h.outbox.events(EventType.AGENT_RECOVERED.value, "a")
    task = await h.task(tid)
    assert task["executions"][0]["orphaned_at"] is None
    await h.tick(20)
    assert await h.state(tid) == S.RUNNING
    await a.result(t)
    assert await h.state(tid) == S.COMPLETED


# ============================================================================================ cancellation


async def test_cancel_task_emits_event_and_late_result_is_not_final() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.ack(t)
    await a.started(t)
    assert await h.manager.cancel_task(tid, "user asked") is True
    await h.pump()
    cancelled = h.outbox.events(EventType.TASK_CANCELLED.value, tid)
    assert cancelled and cancelled[0].data["agent_id"] == "a" and cancelled[0].data["reason"] == "user asked"
    assert any(e.event_type == "task.cancelled" for e in h.bus.events)   # published for agents
    await a.result(t)
    task = await h.task(tid)
    assert task["state"] == S.CANCELLED
    assert task["executions"][0]["status"] == ExecutionStatus.CANCELLED
    assert task["executions"][0]["evidence"][0]["message_type"] == "task.result"
    assert await h.manager.cancel_task(tid, "again") is False


async def test_cancel_blocks_dependants() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("p")
    t1 = await h.manager.create_task(pid, "echo", "one")
    t2 = await h.manager.create_task(pid, "echo", "two", depends_on=[t1])
    await h.manager.cancel_task(t1, "nope")
    assert await h.state(t2) == S.BLOCKED


# ============================================================================================ deliveries


async def test_invalid_and_unsupported_messages_are_rejected() -> None:
    h = await make_harness()
    a = h.agent("old", "echo")
    await a.register(protocol_versions=("2.0",))      # envelope 1.0 is fine, but no shared protocol version
    assert h.bus.deliveries[-1].outcome == "reject"
    assert await h.registry.list() == []
    good = make_envelope(TaskStarted(execution_id="E-1"), sender="x", correlation_id="c")
    bad = good.model_copy(update={"payload": {"oops": True}})   # unvalidated copy -> typed_payload fails
    d_bad = FakeDelivery(bad)
    await h.manager.handle_delivery(d_bad)
    assert d_bad.outcome == "reject"
    d = FakeDelivery(DomainEvent(event_type="task.completed", aggregate_id="T-1"))
    await h.manager.handle_delivery(d)
    assert d.outcome == "ack"                         # not a reply envelope: ignored


async def test_duplicate_result_delivery_has_no_second_effect() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    await a.ack(t)
    await a.result(t)
    completed_version = (await h.task(tid))["state_version"]
    dup = FakeDelivery(h.bus.deliveries[-1].body, attempt=2, redelivered=True)   # broker redelivers
    await h.manager.handle_delivery(dup)
    assert dup.outcome == "ack"
    task = await h.task(tid)
    assert task["state"] == S.COMPLETED and task["state_version"] == completed_version
    assert len(h.outbox.events(EventType.TASK_COMPLETED.value, tid)) == 1


async def test_report_for_unknown_execution_is_acked() -> None:
    h = await make_harness()
    a = h.agent("a", "echo")
    await a.register()
    tid = await single_task(h)
    t = a.take()[0]
    ghost = t.model_copy(update={"execution_id": "E-ghost"})
    await a.result(ghost)
    assert h.bus.deliveries[-1].outcome == "ack"
    assert await h.state(tid) == S.ASSIGNED


# ============================================================================================ hooks / plug-ins


async def test_hooks_dispatch_by_event_and_capability_and_errors_are_contained() -> None:
    seen: list[tuple[str, str]] = []

    @hook("task.completed", capability="echo")
    async def on_echo_done(event: DomainEvent, m: ManagerHandle) -> None:
        seen.append(("echo-done", event.aggregate_id))

    @hook("task.completed", capability="other")
    async def on_other_done(event: DomainEvent, m: ManagerHandle) -> None:
        seen.append(("other-done", event.aggregate_id))

    @hook("task.completed")
    async def broken(event: DomainEvent, m: ManagerHandle) -> None:
        raise RuntimeError("plugin bug")

    @hook("document.uploaded")
    async def on_upload(event: DomainEvent, m: ManagerHandle) -> None:
        tid = await m.create_task(event.project_id or "", "echo", "ingest", inputs={"doc": event.data["doc"]})
        seen.append(("created", (await m.get_task(tid))["inputs"]["doc"]))

    plugin = Plugin(name="p", manager_hooks=[on_echo_done, on_other_done, broken, on_upload])
    h = await make_harness(plugins=[plugin])
    a = h.agent("a", "echo")
    await a.register()
    pid = await h.manager.create_project("p")
    await h.manager.emit(DomainEvent(event_type=EventType.DOCUMENT_UPLOADED.value, aggregate_id="DOC-1",
                                     project_id=pid, data={"doc": "DOC-1"}))
    await h.pump()
    assert seen == [("created", "DOC-1")]
    assert h.outbox.events(EventType.DOCUMENT_UPLOADED.value)
    await a.work_all()
    tid = (await h.manager.list_tasks(pid))[0]["task_id"]
    assert await h.state(tid) == S.COMPLETED
    assert seen[-1] == ("echo-done", tid)
    assert ("other-done", tid) not in seen
    assert [(p, e) for p, e, _ in h.manager.hooks.errors] == [("p", "task.completed")]


async def test_executor_strategy_slot_replaces_default() -> None:
    class HoldEverything(NaiveTopologicalExecutor):
        def ready(self, tasks: list[TaskRecord]) -> list[str]:  # type: ignore[override]
            return []

    h = await make_harness(plugins=[Plugin(name="m3", provides={"executor": HoldEverything})])
    assert isinstance(h.manager.executor, HoldEverything)
    pid = await h.manager.create_project("p")
    tid = await h.manager.create_task(pid, "echo", "x")
    assert await h.state(tid) == S.CREATED


async def test_api_reads() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("alpha")
    tid = await h.manager.create_task(pid, "echo", "x")
    projects = await h.manager.list_projects()
    assert [p["name"] for p in projects] == ["alpha"]
    assert [t["task_id"] for t in await h.manager.list_tasks(pid)] == [tid]
    assert (await h.manager.get_task(tid))["executions"] == []
    assert h.outbox.events(EventType.PROJECT_CREATED.value, pid)
    with pytest.raises(KeyError):
        await h.manager.get_task("T-nope")
    with pytest.raises(KeyError):
        await h.manager.get_project("P-nope")
    await h.manager.stop()

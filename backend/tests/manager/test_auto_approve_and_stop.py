"""Auto-approve (plan shown, then continues without a human gate) and the human's Stop button."""

import pytest

from hmap.core.contracts import DomainEvent, EventType, ExecutionStatus, PlanTask, ProjectState, TaskGraph, TaskState
from hmap.core.plugins import ManagerHandle, Plugin, ProjectStopped, hook
from hmap.manager import InvalidProjectState
from tests.manager.fakes import make_harness, run_until_idle
from tests.manager.test_manager import CAPS, SIX_TASKS

S = TaskState


async def test_auto_approve_shows_the_plan_then_runs_without_a_human() -> None:
    h = await make_harness()
    agents = {cap: h.agent(f"agent-{cap}", cap) for cap in CAPS}
    for a in agents.values():
        await a.register()
    pid = await h.manager.create_project("auto", auto_approve=True)
    await h.manager.submit_graph(pid, SIX_TASKS)            # require_approval=True, as the pipeline calls it
    await h.pump()

    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.EXECUTING and project["auto_approve"] is True
    [approval] = project["approvals"]
    assert approval["status"] == "approved" and approval["comment"] == "auto-approved (project setting)"
    decided = h.outbox.events(EventType.APPROVAL_DECIDED.value, pid)
    assert decided and decided[0].data["auto"] is True and decided[0].data["approved"] is True
    assert not h.outbox.events(EventType.APPROVAL_REQUESTED.value, pid)     # nobody is asked
    assert len(project["plan_task_map"]) == 6                               # the plan is still recorded/shown

    await run_until_idle(h)
    assert (await h.manager.get_project(pid))["state"] == ProjectState.COMPLETED


async def test_default_project_still_waits_for_approval() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("gated")
    await h.manager.submit_graph(pid, SIX_TASKS)
    assert (await h.manager.get_project(pid))["state"] == ProjectState.AWAITING_APPROVAL


async def test_stop_cancels_running_and_waiting_work_and_ignores_late_results() -> None:
    h = await make_harness()
    agents = {cap: h.agent(f"agent-{cap}", cap) for cap in CAPS}
    for a in agents.values():
        await a.register()
    pid = await h.manager.create_project("stop me", auto_approve=True)
    await h.manager.submit_graph(pid, SIX_TASKS)
    await h.pump()
    m = (await h.manager.get_project(pid))["plan_task_map"]
    extract = agents["document.extract"]
    t = extract.take()[0]
    await extract.ack(t)
    await extract.started(t)                                 # A is RUNNING, B..F are waiting

    assert await h.manager.stop_project(pid, "wrong document") == 6
    await h.pump()

    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.CANCELLED and project["stopped_reason"] == "wrong document"
    assert {await h.state(tid) for tid in m.values()} == {S.CANCELLED}
    running = await h.task(m["A"])
    assert running["executions"][0]["status"] == ExecutionStatus.CANCELLED
    cancelled = h.outbox.events(EventType.TASK_CANCELLED.value, m["A"])
    assert cancelled[0].data["agent_id"] == "agent-document.extract" and cancelled[0].data["project_stopped"]
    assert any(e.event_type == "task.cancelled" and e.aggregate_id == m["A"] for e in h.bus.events)  # agents told
    assert h.outbox.events("project.cancelled", pid)[0].data["cancelled_tasks"] == 6

    await extract.result(t)                                  # the agent finishes anyway
    await run_until_idle(h)
    assert await h.state(m["A"]) == S.CANCELLED              # kept as evidence, never final
    assert (await h.manager.get_project(pid))["state"] == ProjectState.CANCELLED
    assert all(not a.take() for a in agents.values())        # nothing new was assigned


async def test_stop_while_waiting_for_approval_closes_the_approval() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("gated")
    await h.manager.submit_graph(pid, SIX_TASKS)
    await h.manager.stop_project(pid)
    project = await h.manager.get_project(pid)
    assert project["approvals"][0]["status"] == "rejected"
    assert project["approvals"][0]["comment"] == "project stopped: stopped by user"
    with pytest.raises(InvalidProjectState):
        await h.manager.approve(pid, True)


async def test_a_stopped_project_accepts_no_new_work() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("p")
    await h.manager.stop_project(pid)
    with pytest.raises(ProjectStopped):
        await h.manager.create_task(pid, "echo", "late")
    with pytest.raises(ProjectStopped):
        await h.manager.submit_graph(pid, SIX_TASKS)
    with pytest.raises(InvalidProjectState):
        await h.manager.stop_project(pid)                    # already stopped
    assert await h.manager.list_tasks(pid) == []


async def test_finished_project_cannot_be_stopped() -> None:
    h = await make_harness()
    a = h.agent("e", "echo")
    await a.register()
    pid = await h.manager.create_project("done", auto_approve=True)
    await h.manager.submit_graph(pid, TaskGraph(project_id=pid, tasks=[
        PlanTask(id="T1", title="x", agent_capability="echo")]))
    await h.pump()
    await run_until_idle(h)
    assert (await h.manager.get_project(pid))["state"] == ProjectState.COMPLETED
    with pytest.raises(InvalidProjectState):
        await h.manager.stop_project(pid)


async def test_hooks_that_fire_after_stop_are_skipped_not_failed() -> None:
    """A late 'extraction finished' style hook tries to add work after Stop: no task, no hook error."""
    calls: list[str] = []

    @hook("project.cancelled")
    async def try_to_continue(event: DomainEvent, manager: ManagerHandle) -> None:
        calls.append(event.event_type)
        await manager.create_task(event.aggregate_id, "echo", "should not run")

    h = await make_harness(plugins=[Plugin(name="late", manager_hooks=[try_to_continue])])
    pid = await h.manager.create_project("p")
    await h.manager.stop_project(pid)
    assert calls == ["project.cancelled"]
    assert await h.manager.list_tasks(pid) == []
    assert h.manager.hooks.errors == []

"""Replanning in the Manager (Sprint 3, requested by Member 3): ``replace_graph`` keeps finished work, retires the
rest, re-gates approval; ``approve(graph_version=)`` refuses decisions about a replaced plan."""

from hmap.core.contracts import PlanTask, ProjectState, TaskGraph, TaskState
from hmap.manager import StaleGraph
from tests.manager.fakes import make_harness

S = TaskState

V1 = TaskGraph(project_id="P-replan", version=1, tasks=[
    PlanTask(id="A", title="Research", agent_capability="research.run"),
    PlanTask(id="B", title="Build", agent_capability="code.implement", depends_on=["A"]),
    PlanTask(id="C", title="Test", agent_capability="test.run", depends_on=["B"]),
    PlanTask(id="R", title="Review", agent_capability="review.final", depends_on=["C"]),
])
V2 = TaskGraph(project_id="P-replan", version=2, tasks=[
    PlanTask(id="A", title="Research", agent_capability="research.run"),
    PlanTask(id="B2", title="Build without X", agent_capability="code.implement", depends_on=["A"]),
    PlanTask(id="C", title="Test", agent_capability="test.run", depends_on=["B2"]),
    PlanTask(id="R", title="Review", agent_capability="review.final", depends_on=["C"]),
])


async def _setup() -> tuple:
    h = await make_harness()
    agents = {c: h.agent(f"agent-{c}", c) for c in ("research.run", "code.implement", "test.run", "review.final")}
    for a in agents.values():
        await a.register()
    pid = await h.manager.create_project("replan")
    await h.manager.submit_graph(pid, V1)
    await h.manager.approve(pid, True, "ok", graph_version=1)
    await h.pump()
    return h, agents, pid


async def test_replace_graph_keeps_completed_work_and_regates_approval() -> None:
    h, agents, pid = await _setup()
    first = (await h.manager.get_project(pid))["plan_task_map"]
    assert await agents["research.run"].work_all() == 1
    await h.pump()
    assert await h.state(first["A"]) == S.COMPLETED
    stale = agents["code.implement"].take()                             # B was already handed to an agent
    assert [t.task_id for t in stale] == [first["B"]]

    mapping = await h.manager.replace_graph(pid, V2)
    await h.pump()
    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.AWAITING_APPROVAL and project["graph_version"] == 2
    assert mapping["A"] == first["A"]                                    # the finished step is the same task
    assert mapping["C"] != first["C"] and mapping["B2"] not in first.values()
    tasks = {t["task_id"]: t for t in await h.manager.list_tasks(pid)}
    assert tasks[first["B"]]["state"] == S.CANCELLED and tasks[first["B"]]["replaced"]
    assert tasks[first["C"]]["replaced"] and not tasks[first["A"]]["replaced"]
    assert {a["graph_version"]: a["status"] for a in project["approvals"]} == {1: "approved", 2: "pending"}

    # a decision about the old version is refused; the new one runs to the end
    try:
        await h.manager.approve(pid, True, graph_version=1)
        raise AssertionError("stale approval accepted")
    except StaleGraph:
        pass
    await h.manager.approve(pid, True, graph_version=2)
    await h.pump()
    for cap in ("code.implement", "test.run", "review.final"):
        assert await agents[cap].work_all() == 1
        await h.pump()
    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.COMPLETED                   # replaced tasks do not fail the run
    decided = h.outbox.events("approval.decided")
    assert decided[-1].data["graph_version"] == 2


async def test_replace_graph_on_a_failed_run_reopens_it() -> None:
    h, agents, pid = await _setup()
    first = (await h.manager.get_project(pid))["plan_task_map"]
    await agents["research.run"].work_all()
    await h.pump()
    agents["code.implement"].take()
    await h.manager.cancel_task(first["B"], "broken")                     # B ends -> C, R blocked -> run FAILED
    await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.FAILED

    retry = V1.model_copy(update={"version": 2})
    await h.manager.replace_graph(pid, retry, require_approval=False)
    await h.pump()
    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.EXECUTING
    for cap in ("code.implement", "test.run", "review.final"):
        assert await agents[cap].work_all() == 1
        await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.COMPLETED


async def test_replace_graph_needs_a_newer_version() -> None:
    h, _, pid = await _setup()
    try:
        await h.manager.replace_graph(pid, V1)
        raise AssertionError("same version accepted")
    except StaleGraph:
        pass


async def test_replace_graph_without_a_plan_submits_it() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("fresh")
    mapping = await h.manager.replace_graph(pid, V1)
    project = await h.manager.get_project(pid)
    assert set(mapping) == {"A", "B", "C", "R"} and project["state"] == ProjectState.AWAITING_APPROVAL

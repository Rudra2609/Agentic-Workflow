"""The layer-parallel executor (3.9) inside the real Manager (fakes for bus and agents): independent steps run at the
same time, the per-project cap holds, blocked steps wait / become BLOCKED, and without the plug-in the Manager keeps
the naive executor."""

from typing import Any

from hmap.agents.planning.executor import LayerParallelExecutor
from hmap.agents.planning.plugin import PLUGIN
from hmap.core.contracts import PlanTask, Priority, ProjectState, TaskGraph, TaskState
from hmap.core.plugins import Plugin
from hmap.manager import NaiveTopologicalExecutor
from hmap.manager.hooks import resolve_strategy
from tests.manager.fakes import make_harness

S = TaskState

# design -> three independent builds (b3 most urgent) -> review
WIDE = TaskGraph(project_id="P-wide", tasks=[
    PlanTask(id="design", title="Design", agent_capability="code.implement", phase="design"),
    PlanTask(id="b1", title="Build 1", agent_capability="code.implement", depends_on=["design"]),
    PlanTask(id="b2", title="Build 2", agent_capability="code.implement", depends_on=["design"]),
    PlanTask(id="b3", title="Build 3", agent_capability="code.implement", depends_on=["design"],
             priority=Priority.URGENT),
    PlanTask(id="review", title="Review", agent_capability="review.final", depends_on=["b1", "b2", "b3"],
             phase="review"),
])


def planning(max_parallel: int) -> Plugin:
    return Plugin(name="planning-test", provides={"executor": LayerParallelExecutor(max_parallel=max_parallel)})


def test_the_plugin_provides_the_executor_and_the_naive_one_stays_the_default() -> None:
    assert isinstance(resolve_strategy([PLUGIN], "executor", NaiveTopologicalExecutor()), LayerParallelExecutor)
    assert type(resolve_strategy([], "executor", NaiveTopologicalExecutor())) is NaiveTopologicalExecutor


def test_order_is_layer_by_layer_most_urgent_first() -> None:
    assert LayerParallelExecutor(4).order(WIDE) == ["design", "b3", "b1", "b2", "review"]


async def _run(max_parallel: int) -> tuple[Any, Any, Any, str, dict[str, str]]:
    h = await make_harness(plugins=[planning(max_parallel)])
    coder = h.agent("coder", "code.implement", max_slots=8)
    reviewer = h.agent("reviewer", "review.final")
    await coder.register()
    await reviewer.register()
    pid = await h.manager.create_project("wide")
    await h.manager.submit_graph(pid, WIDE, require_approval=False)
    await h.pump()
    m = (await h.manager.get_project(pid))["plan_task_map"]
    assert await coder.work_all() == 1          # design
    await h.pump()
    return h, coder, reviewer, pid, m


async def test_independent_steps_run_at_the_same_time() -> None:
    h, coder, reviewer, pid, m = await _run(max_parallel=4)
    batch = coder.take()
    assert {t.task_id for t in batch} == {m["b1"], m["b2"], m["b3"]}      # all three handed out together
    assert batch[0].task_id == m["b3"]                                     # the urgent one first
    for t in batch:
        await coder.started(t)
    states = [await h.state(m[k]) for k in ("b1", "b2", "b3")]
    assert states == [S.RUNNING] * 3                                       # overlapping in time
    for t in batch:
        await coder.complete(t)
    await h.pump()
    assert await reviewer.work_all() == 1
    await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.COMPLETED


async def test_the_cap_limits_running_steps_per_project() -> None:
    h, coder, _, _, m = await _run(max_parallel=2)
    first = coder.take()
    assert len(first) == 2 and m["b3"] in {t.task_id for t in first}       # cap 2: the urgent one is in
    waiting = next(k for k in ("b1", "b2") if m[k] not in {t.task_id for t in first})
    assert await h.state(m[waiting]) == S.CREATED                         # held back, not failed
    await coder.complete(first[0])
    await h.pump()
    assert [t.task_id for t in coder.take()] == [m[waiting]]               # a slot freed -> it starts


async def test_failed_step_blocks_its_dependants_only() -> None:
    h, coder, _, pid, m = await _run(max_parallel=4)
    batch = {t.task_id: t for t in coder.take()}
    await h.manager.cancel_task(m["b1"], "broken")
    for k in ("b2", "b3"):
        await coder.complete(batch[m[k]])
    await h.pump()
    assert await h.state(m["review"]) == S.BLOCKED
    assert (await h.manager.get_project(pid))["state"] == ProjectState.FAILED


async def test_pipeline_steps_are_never_capped() -> None:
    h = await make_harness(plugins=[planning(1)])
    agent = h.agent("echo", "echo", max_slots=4)
    await agent.register()
    pid = await h.manager.create_project("free")
    for _ in range(3):
        await h.manager.create_task(pid, "echo", "not a plan step")
    await h.pump()
    assert len(agent.take()) == 3

"""DLQ replay (Sprint 4 item 4.18, plan D18, requested by Member 4): an operator replays a dead-lettered task as a NEW
execution, explicitly and audited; the waiting tasks and the project are re-evaluated. Also the refine flag (D3)."""

import pytest

from hmap.core.contracts import PlanTask, ProjectState, TaskGraph, TaskState
from hmap.core.errors import ErrorCode
from hmap.core.plugins import ProjectStopped
from hmap.manager import InvalidTaskState, ManagerConfig, UnknownTask
from hmap.manager.transitions import ALLOWED, OPERATOR_TRANSITIONS, TransitionError, check_transition
from tests.manager.fakes import make_harness

S = TaskState
CONFIG = ManagerConfig(retry_delays_s=(1.0,), retry_jitter=0.0, max_retries=1)
GRAPH = TaskGraph(project_id="P", tasks=[
    PlanTask(id="A", title="Fetch", agent_capability="research.run"),
    PlanTask(id="B", title="Use it", agent_capability="code.implement", depends_on=["A"]),
    PlanTask(id="C", title="Check it", agent_capability="test.run", depends_on=["B"])])


async def _dead_lettered():
    h = await make_harness(config=CONFIG)
    research = h.agent("agent-r", "research.run")
    for a in (research, h.agent("agent-c", "code.implement"), h.agent("agent-t", "test.run")):
        await a.register()
    pid = await h.manager.create_project("dlq")
    await h.manager.submit_graph(pid, GRAPH, require_approval=False)
    await h.pump()
    ids = (await h.manager.get_project(pid))["plan_task_map"]
    for _ in range(2):                                         # first try + 1 retry, both fail
        [t] = research.take()
        await research.ack(t)
        await research.error(t, ErrorCode.TOOL_TRANSIENT)
        await h.tick(2.0)
    assert await h.state(ids["A"]) == S.DEAD_LETTERED
    assert await h.state(ids["B"]) == S.BLOCKED and await h.state(ids["C"]) == S.BLOCKED
    assert (await h.manager.get_project(pid))["state"] == ProjectState.FAILED
    return h, research, pid, ids


def test_operator_edges_are_not_in_the_normal_table() -> None:
    assert ALLOWED[S.DEAD_LETTERED] == set() and S.CREATED not in ALLOWED[S.BLOCKED]
    with pytest.raises(TransitionError):
        check_transition(S.DEAD_LETTERED, S.READY)
    check_transition(S.DEAD_LETTERED, S.READY, operator=True)
    assert {S.DEAD_LETTERED: {S.READY}, S.BLOCKED: {S.CREATED}} == OPERATOR_TRANSITIONS
    with pytest.raises(TransitionError):
        check_transition(S.COMPLETED, S.READY, operator=True)


async def test_replay_is_a_new_execution_and_unblocks_the_rest() -> None:
    h, research, pid, ids = await _dead_lettered()
    before = await h.task(ids["A"])
    old_executions = {e["execution_id"] for e in before["executions"]}
    out = await h.manager.replay_dead_letter(ids["A"], operator="user:ada", reason="the source site is back")
    await h.pump()
    assert out["replay"] == 1 and sorted(out["unblocked"]) == sorted([ids["B"], ids["C"]])
    after = await h.task(ids["A"])
    assert after["state"] == S.ASSIGNED and after["retries"] == 0 and after["replays"] == 1
    [new] = [e for e in after["executions"] if e["execution_id"] not in old_executions]
    assert new["attempt"] == before["attempts"] + 1 and new["status"] == "PENDING"
    assert any(e["status"] == "DEAD_LETTERED" for e in after["executions"])     # history kept
    assert (await h.manager.get_project(pid))["state"] == ProjectState.EXECUTING
    assert await h.state(ids["B"]) == S.CREATED
    events = [r.body for r in h.outbox.rows if r.kind == "event"]
    replayed = [e for e in events if e.event_type == "task.replayed"]
    assert replayed and replayed[0].data["by"] == "user:ada" and replayed[0].data["reason"] == "the source site is back"
    # the new attempt succeeds -> the rest of the graph runs
    [t] = research.take()
    assert t.execution_id == new["execution_id"]
    await research.complete(t)
    for agent in h.agents[1:]:
        await agent.work_all()
        await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.COMPLETED


async def test_replay_refusals() -> None:
    h, _research, _pid, ids = await _dead_lettered()
    with pytest.raises(InvalidTaskState):
        await h.manager.replay_dead_letter(ids["B"], operator="u", reason="r")      # BLOCKED, not dead-lettered
    with pytest.raises(ValueError):
        await h.manager.replay_dead_letter(ids["A"], operator="u", reason="  ")      # a reason is required
    with pytest.raises(UnknownTask):
        await h.manager.replay_dead_letter("T-nope", operator="u", reason="r")
    await h.manager.replay_dead_letter(ids["A"], operator="u", reason="first")
    with pytest.raises(InvalidTaskState):                                           # not twice
        await h.manager.replay_dead_letter(ids["A"], operator="u", reason="again")


async def test_no_replay_in_a_stopped_project() -> None:
    h, _research, pid, ids = await _dead_lettered()
    await h.manager.start_run(pid, goal="again")                  # a FAILED project may run again ...
    await h.manager.stop_project(pid, "enough")                    # ... and be stopped
    with pytest.raises(ProjectStopped):
        await h.manager.replay_dead_letter(ids["A"], operator="u", reason="r")


async def test_refine_setting_reaches_the_assignment() -> None:
    h = await make_harness()
    agent = h.agent("agent-e", "echo", max_slots=5)
    await agent.register()
    plain = await h.manager.create_project("plain")
    refined = await h.manager.create_project("refined", refine=True)
    await h.manager.create_task(plain, "echo", "a")
    await h.manager.create_task(refined, "echo", "b")
    await h.manager.create_task(refined, "echo", "c", inputs={"refine": False})       # per-task override
    await h.pump()
    got = {t.objective: t.refine for t in agent.take()}
    assert got == {"a": False, "b": True, "c": False}
    assert (await h.manager.update_project(plain, refine=True))["refine"] is True
    await h.manager.create_task(plain, "echo", "d")
    await h.pump()
    assert [t.refine for t in agent.take()] == [True]

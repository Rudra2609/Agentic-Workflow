""""Why did this task fail?" on every Sprint-1 chaos scenario (item 4.16): agent crash mid-task, duplicate delivery,
retries exhausted -> dead letter, Manager restart with outbox replay, a late report after completion. Same set-ups
as ``tests/e2e/test_chaos.py``; here the explanation is checked."""

import asyncio

from hmap.agents.ops.explain import explain
from hmap.core.bus.outbox import OutboxPublisher
from hmap.core.contracts import ProjectState, TaskStarted, TaskState, make_envelope
from hmap.core.plugins import Plugin
from hmap.core.runtime.discovery import discover
from hmap.manager.manager import Manager
from tests.e2e.test_chaos import FAST, FlakyAgent, crash, graph, project_state, wait_for

JAEGER = "http://127.0.0.1:16686"


async def why(s, task_id: str) -> dict:
    return await explain(s, task_id, jaeger_url=JAEGER, tracing=False)


async def test_crash_mid_task_is_explained_as_a_lost_agent_then_success(make_system) -> None:
    s = await make_system()
    first = s.host
    second = await s.start_agents()
    s.extra_hosts = [first]
    m = s.manager
    pid = await m.create_project("crash")
    await m.submit_graph(pid, graph(pid, ("T1", "research.run", [], {})), require_approval=True)
    [task] = await m.list_tasks(pid)
    async with m.store.transaction() as tx:
        rec = await m.store.get_task(task["task_id"])
        rec.inputs = {**rec.inputs, "stub_delay_s": 1.0}
        await tx.update_task(rec, expected_version=rec.state_version)
    await m.approve(pid, True)

    async def running() -> bool:
        return any(w.current_execution_ids for w in [*first.workers, *second.workers])

    await wait_for(running)
    victim = next(w for w in [*first.workers, *second.workers] if w.current_execution_ids)
    await crash(victim)

    async def done() -> bool:
        return await project_state(m, pid) == ProjectState.COMPLETED

    await wait_for(done)
    out = await why(s, task["task_id"])
    v = out["verdict"]
    assert v["status"] == "completed" and "attempt 2" in v["headline"]
    assert any("lost their agent" in f for f in v["facts"])
    assert len(out["executions"]) == 2 and out["executions"][0]["status"] in ("TIMED_OUT", "SUPERSEDED")
    assert out["executions"][0]["agent_id"] == victim.agent_id
    assert len(out["messages"]) == 2 and all(msg["published_at"] for msg in out["messages"])
    assert any(e["event_type"] == "task.retrying" for e in out["timeline"])
    assert out["trace"]["links"][0].startswith(f"{JAEGER}/trace/") and out["artifacts"]


async def test_duplicate_delivery_is_explained_as_processed_once(make_system) -> None:
    s = await make_system()
    m = s.manager
    pid = await m.create_project("dup")
    await m.submit_graph(pid, graph(pid, ("T1", "echo", [], {})), require_approval=False)

    async def done() -> bool:
        return await project_state(m, pid) == ProjectState.COMPLETED

    await wait_for(done)
    [row] = [r for r in await s.outbox.all_rows() if r.kind == "command"]
    await s.bus.send_command("echo", row.body)                      # the broker redelivers it
    await asyncio.sleep(0.3)
    [task] = await m.list_tasks(pid)
    out = await why(s, task["task_id"])
    assert out["verdict"]["status"] == "completed" and "attempt 1" in out["verdict"]["headline"]
    [msg] = out["messages"]
    assert msg["message_id"] == row.body.message_id and msg["processed_by"] == ["agent:echo"]
    assert len(out["executions"]) == 1


async def test_dead_letter_is_explained_with_its_cause_and_the_blocked_steps(make_system) -> None:
    FlakyAgent.calls = 0
    s = await make_system([*discover(), Plugin(name="flaky", agents=[FlakyAgent], priority=100)])
    m = s.manager
    pid = await m.create_project("dlq")
    await m.submit_graph(pid, graph(pid, ("T1", "flaky.op", [], {}), ("T2", "echo", ["T1"], {})),
                         require_approval=False)
    ids = {t["plan_task_id"]: t["task_id"] for t in await m.list_tasks(pid)}

    async def settled() -> bool:
        states = {t["plan_task_id"]: t["state"] for t in await m.list_tasks(pid)}
        return states.get("T1") == TaskState.DEAD_LETTERED and states.get("T2") == TaskState.BLOCKED

    await wait_for(settled)
    out = await why(s, ids["T1"])
    v = out["verdict"]
    attempts = 1 + FAST.manager.max_retries
    assert v["status"] == "dead_lettered" and f"after {attempts} attempt(s)" in v["headline"]
    assert "temporary tool or network error" in v["headline"] and v["cause"] == "TOOL_TRANSIENT"
    assert any(f"TOOL_TRANSIENT x{attempts}" in f for f in v["facts"])
    assert any("blocked" in f for f in v["facts"])
    assert {a["action"]: a["allowed"] for a in v["actions"]}["replay"] is True
    assert [e["status"] for e in out["executions"]][-1] == "DEAD_LETTERED"
    assert out["dependants"] == [{"task_id": ids["T2"], "title": "T2", "state": "BLOCKED"}]
    blocked = await why(s, ids["T2"])
    assert blocked["verdict"]["status"] == "blocked" and "T1" in blocked["verdict"]["headline"]


async def test_manager_restart_is_explained_by_the_replayed_outbox(make_system) -> None:
    s = await make_system()
    s.publisher.stop()
    assert s._publisher_task is not None
    s._publisher_task.cancel()
    m = s.manager
    pid = await m.create_project("restart")
    await m.submit_graph(pid, graph(pid, ("T1", "echo", [], {})), require_approval=False)
    [task] = await m.list_tasks(pid)

    async def assigned() -> bool:
        return (await m.get_task(task["task_id"]))["state"] == TaskState.ASSIGNED

    await wait_for(assigned)
    out = await why(s, task["task_id"])
    assert out["verdict"]["status"] == "running"                              # assigned, never sent
    assert [msg["published_at"] for msg in out["messages"]] == [None]
    await m.stop()
    m2 = Manager(bus=s.bus, store=s.store, outbox=s.outbox, registry=s.registry, artifacts=s.artifacts,
                 contexts=s.contexts, plugins=s.plugins, config=FAST.manager)
    await m2.start(watchdog_interval_s=0.05)
    s.manager = m2
    s.publisher = OutboxPublisher(s.outbox, s.bus)
    s._publisher_task = asyncio.create_task(s.publisher.run_forever(0.05))

    async def done() -> bool:
        return await project_state(m2, pid) == ProjectState.COMPLETED

    await wait_for(done)
    out = await why(s, task["task_id"])
    assert out["verdict"]["status"] == "completed" and out["messages"][0]["published_at"] is not None


async def test_late_report_is_kept_as_evidence_and_explained(make_system) -> None:
    s = await make_system()
    m = s.manager
    pid = await m.create_project("late")
    await m.submit_graph(pid, graph(pid, ("T1", "echo", [], {})), require_approval=False)

    async def done() -> bool:
        return await project_state(m, pid) == ProjectState.COMPLETED

    await wait_for(done)
    [task] = await m.list_tasks(pid)
    exe = (await m.get_task(task["task_id"]))["executions"][-1]
    late = make_envelope(TaskStarted(execution_id=exe["execution_id"]), sender=exe["agent_id"] or "x",
                         correlation_id=pid, task_id=task["task_id"])
    await s.bus.send_reply(late)

    async def evidence() -> bool:
        return bool((await m.get_task(task["task_id"]))["executions"][-1]["evidence"])

    await wait_for(evidence)
    out = await why(s, task["task_id"])
    assert out["verdict"]["status"] == "completed"
    assert any("late or duplicate report" in f for f in out["verdict"]["facts"])
    assert out["executions"][-1]["late_reports"][0]["message_type"] == "task.started"

"""Runs (history is never overwritten), failure while understanding the request, archive and delete."""

import pytest

from hmap.core.contracts import EventType, PlanTask, ProjectState, TaskGraph, TaskState
from hmap.core.errors import ErrorCode
from hmap.manager import InvalidProjectState, UnknownProject
from tests.manager.fakes import make_harness, run_until_idle

S = TaskState
ONE = [PlanTask(id="T1", title="Implement", agent_capability="code.implement")]


async def _complete_run(h, pid: str) -> None:
    await h.manager.submit_graph(pid, TaskGraph(project_id=pid, tasks=ONE))
    await h.pump()
    await run_until_idle(h)


async def test_second_run_keeps_the_first_runs_history() -> None:
    h = await make_harness()
    await h.agent("coder", "code.implement").register()
    pid = await h.manager.create_project("p", auto_approve=True, owner_id="U-1")
    assert await h.manager.start_run(pid, goal="first") == 1
    assert (await h.manager.get_project(pid))["state"] == ProjectState.INGESTING
    await _complete_run(h, pid)
    first = await h.manager.get_project(pid)
    assert first["state"] == ProjectState.COMPLETED and first["runs"][0]["outcome"] == ProjectState.COMPLETED

    assert await h.manager.start_run(pid, goal="second", documents=["v2.pdf"]) == 2
    await _complete_run(h, pid)
    project = await h.manager.get_project(pid)
    assert [r["number"] for r in project["runs"]] == [1, 2]
    assert [r["goal"] for r in project["runs"]] == ["first", "second"] and project["runs"][1]["documents"] == ["v2.pdf"]
    tasks = await h.manager.list_tasks(pid)
    assert sorted(t["run"] for t in tasks) == [1, 2] and all(t["state"] == S.COMPLETED for t in tasks)


async def test_a_new_run_waits_until_the_current_one_is_done_or_stopped() -> None:
    h = await make_harness()
    pid = await h.manager.create_project("p")
    await h.manager.start_run(pid, goal="x")
    with pytest.raises(InvalidProjectState):
        await h.manager.start_run(pid, goal="y")
    await h.manager.stop_project(pid)
    project = await h.manager.get_project(pid)
    assert project["runs"][0]["outcome"] == ProjectState.CANCELLED and project["runs"][0]["finished_at"]
    assert await h.manager.start_run(pid, goal="y") == 2            # a stopped project can run again
    assert (await h.manager.get_project(pid))["stopped_reason"] is None
    tid = await h.manager.create_task(pid, "echo", "accepted again")
    assert (await h.task(tid))["run"] == 2


async def test_previous_run_failures_do_not_decide_the_new_run() -> None:
    h = await make_harness()
    coder = h.agent("coder", "code.implement")
    await coder.register()
    pid = await h.manager.create_project("p", auto_approve=True)
    await h.manager.start_run(pid)
    await h.manager.submit_graph(pid, TaskGraph(project_id=pid, tasks=ONE))
    await h.pump()
    t = coder.take()[0]
    await coder.error(t, ErrorCode.WRONG_RESULT)                    # non-retryable -> FAILED
    await h.pump()
    assert (await h.manager.get_project(pid))["state"] == ProjectState.FAILED
    await h.manager.start_run(pid)
    await _complete_run(h, pid)
    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.COMPLETED
    assert [r["outcome"] for r in project["runs"]] == [ProjectState.FAILED, ProjectState.COMPLETED]


async def test_failure_while_understanding_the_request_fails_the_run() -> None:
    h = await make_harness()
    extractor = h.agent("ex", "document.extract")
    await extractor.register()
    pid = await h.manager.create_project("p")
    await h.manager.start_run(pid, documents=["broken.pdf"])
    await h.manager.create_task(pid, "document.extract", "read it")
    await h.pump()
    t = extractor.take()[0]
    await extractor.error(t, ErrorCode.INVALID_MESSAGE)
    await h.pump()
    project = await h.manager.get_project(pid)
    assert project["state"] == ProjectState.FAILED and project["runs"][0]["outcome"] == ProjectState.FAILED


async def test_owner_filter_archive_and_delete() -> None:
    h = await make_harness()
    a = await h.manager.create_project("a", owner_id="U-a")
    b = await h.manager.create_project("b", owner_id="U-b")
    assert [p["project_id"] for p in await h.manager.list_projects(owner_id="U-a")] == [a]
    archived = await h.manager.update_project(a, archived=True, name="a2")
    assert archived["archived"] is True and archived["name"] == "a2"
    await h.manager.start_run(b)
    tid = await h.manager.create_task(b, "echo", "work")
    await h.manager.delete_project(b)                                 # stops the running work first
    with pytest.raises(UnknownProject):
        await h.manager.get_project(b)
    assert [p["project_id"] for p in await h.manager.list_projects()] == [a]
    assert (await h.task(tid))["state"] == S.CANCELLED
    assert h.outbox.events("project.deleted", b)
    assert h.outbox.events(EventType.TASK_CANCELLED.value, tid)


async def test_local_only_project_assignments_say_so_and_follow_a_later_switch() -> None:
    h = await make_harness()
    a = h.agent("echo-1", "echo")
    await a.register()
    private = await h.manager.create_project("private", cloud_ok=False)
    assert (await h.manager.get_project(private))["cloud_ok"] is False
    await h.manager.create_task(private, "echo", "first")
    await h.pump()
    [first] = a.take()
    assert first.cloud_ok is False
    await a.complete(first)

    await h.manager.update_project(private, cloud_ok=True)       # applies to steps assigned after the switch
    await h.manager.create_task(private, "echo", "second")
    await h.pump()
    [second] = a.take()
    assert second.cloud_ok is True
    shared = await h.manager.create_project("shared")
    assert (await h.manager.get_project(shared))["cloud_ok"] is True   # the default (doc 02 §2.5)

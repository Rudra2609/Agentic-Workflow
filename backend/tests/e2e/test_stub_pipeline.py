"""End-to-end (Sprint 1 DoD): Manager + real in-memory bus + outbox publisher + registry + stub agents.

A TaskGraph is submitted, waits for human approval, then every task runs on a stub agent over the bus and the
project completes. Everything is wired through HmapSystem exactly as `make agents` + API will be in the demo.
"""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from hmap.core.contracts import ProjectState, TaskState
from hmap.core.contracts.examples import TASK_GRAPH
from hmap.system import HmapSystem, SystemConfig


async def wait_for(cond: Callable[[], Any], timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await cond():
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


@pytest.fixture
async def system(tmp_path):
    s = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts",
                             config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.1))
    await s.start(with_agents=True)
    yield s
    await s.stop()


async def test_graph_runs_through_stubs_after_approval(system: HmapSystem) -> None:
    m = system.manager
    pid = await m.create_project("tcp chat demo")
    await m.submit_graph(pid, TASK_GRAPH.model_copy(update={"project_id": pid}), require_approval=True)

    await asyncio.sleep(0.3)  # nothing may run before approval
    assert (await m.get_project(pid))["state"] == ProjectState.AWAITING_APPROVAL
    assert all(t["state"] in (TaskState.CREATED, TaskState.READY) for t in await m.list_tasks(pid))

    await m.approve(pid, True, "looks good")

    async def done() -> bool:
        return (await m.get_project(pid))["state"] == ProjectState.COMPLETED

    await wait_for(done)
    tasks = await m.list_tasks(pid)
    assert len(tasks) == 5 and all(t["state"] == TaskState.COMPLETED for t in tasks)
    # every task produced a verifiable artifact in the store
    for t in tasks:
        detail = await m.get_task(t["task_id"])
        refs = [r for e in detail["executions"] for r in e["result_refs"]]
        assert refs, t
        data = await system.artifacts.get(_ref(refs[0]), project_id=pid)
        assert data


def _ref(raw: Any):
    from hmap.core.contracts import ArtifactRef
    return raw if isinstance(raw, ArtifactRef) else ArtifactRef.model_validate(raw)


async def test_all_stub_agents_register(system: HmapSystem) -> None:
    async def registered() -> bool:
        return len(await system.registry.list()) >= 9
    await wait_for(registered)
    caps = {c for a in await system.registry.list() for c in a.capabilities}
    assert {"document.extract", "plan.generate", "research.run", "review.final", "echo"} <= caps

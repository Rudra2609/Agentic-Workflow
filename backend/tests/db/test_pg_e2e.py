"""End-to-end on Postgres: the same pipeline as ``tests/e2e/test_stub_pipeline.py`` (Manager + in-memory bus + outbox
publisher + stub agents running the example TaskGraph), but with task state, outbox, inbox, registry and contexts in
Postgres. Wired by hand here (``HmapSystem`` is in-memory only for now)."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from hmap.core.bus.memory import InMemoryBus
from hmap.core.bus.outbox import OutboxPublisher
from hmap.core.bus.pg_stores import PostgresInboxStore
from hmap.core.contracts import ArtifactRef, ProjectState, TaskState
from hmap.core.contracts.examples import TASK_GRAPH
from hmap.core.llm import FakeLLM
from hmap.core.runtime.discovery import discover
from hmap.core.runtime.host import AgentHost, HostDeps
from hmap.db import Database
from hmap.manager.config import ManagerConfig
from hmap.manager.manager import Manager
from hmap.manager.pg_store import PostgresTaskStore
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.services.context.pg import PostgresContextStore
from hmap.services.registry.pg import PostgresRegistry

pytestmark = pytest.mark.integration


@dataclass
class PgSystem:
    db: Database
    bus: InMemoryBus
    store: PostgresTaskStore
    registry: PostgresRegistry
    artifacts: LocalFSArtifactStore
    manager: Manager


async def wait_for(cond: Callable[[], Awaitable[bool]], timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


@pytest.fixture
async def system(db: Database, tmp_path: Path) -> AsyncIterator[PgSystem]:
    bus = InMemoryBus()
    store = PostgresTaskStore(db)
    registry = PostgresRegistry(db, lease_s=30)
    contexts = PostgresContextStore(db)
    artifacts = LocalFSArtifactStore(tmp_path / "artifacts")
    plugins = discover()
    manager = Manager(bus=bus, store=store, outbox=store.outbox, registry=registry, artifacts=artifacts,
                      contexts=contexts, plugins=plugins, config=ManagerConfig(), inbox=PostgresInboxStore(db))
    publisher = OutboxPublisher(store.outbox, bus)
    host = AgentHost(plugins, HostDeps(bus=bus, llm=FakeLLM(), artifacts=artifacts, contexts=contexts,
                                       inbox=PostgresInboxStore(db), owns_bus=False), heartbeat_s=0.2)
    await bus.start()
    await manager.start(watchdog_interval_s=0.1)
    publisher_task = asyncio.create_task(publisher.run_forever(0.05))
    await host.start()
    try:
        yield PgSystem(db, bus, store, registry, artifacts, manager)
    finally:
        await host.stop()
        await manager.stop()
        publisher.stop()
        publisher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await publisher_task
        await publisher.run_once()
        await bus.close()


async def test_graph_runs_to_completed_on_postgres(system: PgSystem) -> None:
    m = system.manager
    pid = await m.create_project("tcp chat demo (postgres)")
    await m.submit_graph(pid, TASK_GRAPH.model_copy(update={"project_id": pid}), require_approval=True)

    await asyncio.sleep(0.3)  # nothing may run before approval
    assert (await m.get_project(pid))["state"] == ProjectState.AWAITING_APPROVAL
    assert all(t["state"] in (TaskState.CREATED, TaskState.READY) for t in await m.list_tasks(pid))

    await m.approve(pid, True, "looks good")

    async def done() -> bool:
        return bool((await m.get_project(pid))["state"] == ProjectState.COMPLETED)

    await wait_for(done)
    tasks = await m.list_tasks(pid)
    assert len(tasks) == 5 and all(t["state"] == TaskState.COMPLETED for t in tasks)
    for t in tasks:
        detail = await m.get_task(t["task_id"])
        refs = [r for e in detail["executions"] for r in e["result_refs"]]
        assert refs, t
        ref = refs[0] if isinstance(refs[0], ArtifactRef) else ArtifactRef.model_validate(refs[0])
        assert await system.artifacts.get(ref, project_id=pid)

    # durable state really is in Postgres: a fresh store on the same database sees it
    fresh = PostgresTaskStore(system.db)
    project = await fresh.get_project(pid)
    assert project is not None and project.state == ProjectState.COMPLETED
    assert {t.state for t in await fresh.list_tasks(project_id=pid)} == {TaskState.COMPLETED}
    events = await system.db.fetch("SELECT event_type FROM events WHERE project_id = %s ORDER BY seq", (pid,))
    assert events[0]["event_type"] == "project.created" and events[-1]["event_type"] == "project.completed"
    assert len(await system.registry.list()) >= 9
    assert (await system.db.fetch("SELECT count(*) AS n FROM inbox"))[0]["n"] > 0

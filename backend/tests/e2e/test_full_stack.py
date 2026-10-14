"""Full stack (Sprint 1 DoD): API -> Manager on PostgreSQL -> RabbitMQ -> stub agents -> back, no in-memory adapters.

Isolated: a fresh Postgres schema and a random RabbitMQ namespace per test module; skipped (with the reason) when
`make infra-up` has not been run.
"""

import asyncio
import time
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.bus.inbox import InMemoryInboxStore
from hmap.core.bus.outbox import OutboxPublisher
from hmap.core.bus.pg_stores import PostgresInboxStore
from hmap.core.contracts import ProjectState
from hmap.core.contracts.domain import PlanTask, TaskGraph
from hmap.core.llm import FakeLLM
from hmap.core.runtime.discovery import discover
from hmap.db import Database, upgrade
from hmap.manager.config import ManagerConfig
from hmap.manager.manager import Manager
from hmap.manager.pg_store import PostgresTaskStore
from hmap.services.accounts.pg import PostgresAccountStore
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.services.context.pg import PostgresContextStore
from hmap.services.registry.pg import PostgresRegistry
from hmap.system import HmapSystem, Persistence, SystemConfig
from tests.api.helpers import signed_in
from tests.core.bus.conftest import delete_namespace, make_rabbit_bus, new_namespace, rabbitmq_unreachable_reason
from tests.db.conftest import _unreachable_reason, database_url_for_tests, drop_schema

pytestmark = pytest.mark.integration

CFG = SystemConfig(lease_s=2.0, heartbeat_s=0.2, watchdog_interval_s=0.1,
                   manager=ManagerConfig(retry_delays_s=(0.1, 0.1, 0.1), retry_jitter=0.0))


@pytest.fixture(scope="module")
def infra() -> Iterator[tuple[str, str]]:
    url = database_url_for_tests()
    reason = _unreachable_reason(url) or rabbitmq_unreachable_reason()
    if reason:
        pytest.skip(reason)
    schema = f"hmap_e2e_{uuid.uuid4().hex[:10]}"
    upgrade(url, schema=schema)
    try:
        yield url, schema
    finally:
        drop_schema(url, schema)


def persistence(url: str, schema: str) -> Persistence:
    db = Database(url, schema=schema, max_size=20)
    store = PostgresTaskStore(db)
    return Persistence(store=store, outbox=store.outbox, contexts=PostgresContextStore(db),
                       registry=PostgresRegistry(db, lease_s=CFG.lease_s), manager_inbox=PostgresInboxStore(db),
                       agent_inbox=PostgresInboxStore(db), accounts=PostgresAccountStore(db), db=db)


@pytest.fixture
def system(infra, tmp_path) -> Iterator[tuple[HmapSystem, str]]:
    url, schema = infra
    ns = new_namespace()
    s = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"), llm=FakeLLM(),
                   plugins=discover(), config=CFG, persistence=persistence(url, schema))
    yield s, ns
    asyncio.run(delete_namespace(ns))


def poll(client: TestClient, url: str, pred, timeout: float = 30.0):
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = client.get(url).json()
        if pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting on {url}: {body}")


def test_upload_to_completion_over_rabbitmq_and_postgres(system) -> None:
    s, _ = system
    with TestClient(create_app(s, run_agents=True)) as client:
        signed_in(client)
        poll(client, "/api/agents", lambda a: len(a) >= 9)
        pid = client.post("/api/projects", json={"name": "full stack"}).json()["project_id"]
        r = client.post(f"/api/projects/{pid}/documents",
                        files={"file": ("a.txt", b"The server must accept 10 clients.", "text/plain")})
        assert r.status_code == 201
        poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
        client.post(f"/api/projects/{pid}/approval", json={"approved": True})
        poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
        tasks = client.get(f"/api/projects/{pid}/tasks").json()
        assert tasks and all(t["state"] == "COMPLETED" for t in tasks)
        depths = client.get("/api/health").json()["queues"]
        assert depths.get("hmap.dlq", 0) == 0


def test_auto_approve_and_stop_survive_in_postgres(system) -> None:
    """Auto mode runs to COMPLETED with no approval call; Stop cancels a waiting plan. Both persisted in Postgres."""
    s, _ = system
    with TestClient(create_app(s, run_agents=True)) as client:
        signed_in(client)
        poll(client, "/api/agents", lambda a: len(a) >= 9)
        auto = client.post("/api/projects", json={"name": "auto", "auto_approve": True}).json()["project_id"]
        client.post(f"/api/projects/{auto}/documents", files={"file": ("a.txt", b"Must work.", "text/plain")})
        done = poll(client, f"/api/projects/{auto}", lambda p: p["state"] == "COMPLETED")
        assert done["auto_approve"] is True and [a["status"] for a in done["approvals"]] == ["approved"]

        gated = client.post("/api/projects", json={"name": "gated"}).json()["project_id"]
        client.post(f"/api/projects/{gated}/documents", files={"file": ("b.txt", b"Must work.", "text/plain")})
        poll(client, f"/api/projects/{gated}", lambda p: p["state"] == "AWAITING_APPROVAL")
        r = client.post(f"/api/projects/{gated}/stop", json={"reason": "e2e"})
        steps = len(client.get(f"/api/planning/plan/{gated}").json()["graph"]["tasks"])  # Member 3's plan
        assert r.status_code == 200 and r.json()["cancelled_tasks"] == steps
        stopped = client.get(f"/api/projects/{gated}").json()
        assert stopped["state"] == "CANCELLED" and stopped["stopped_reason"] == "e2e"
        assert stopped["approvals"][0]["status"] == "rejected"


def test_workspace_survives_a_server_restart(infra, tmp_path) -> None:
    """Sign in, create a project, restart the whole server on the same database: the session still works, the
    project, its run history and its files are still there, and the activity history was reloaded."""
    url, schema = infra
    artifacts = tmp_path / "artifacts"

    def build() -> HmapSystem:
        return HmapSystem(bus=make_rabbit_bus(new_namespace()), artifacts=LocalFSArtifactStore(artifacts),
                          llm=FakeLLM(), plugins=discover(), config=CFG, persistence=persistence(url, schema))

    first = build()
    with TestClient(create_app(first, run_agents=True)) as client:
        signed_in(client, email="restart@example.test")
        poll(client, "/api/agents", lambda a: len(a) >= 9)
        pid = client.post("/api/projects", json={"name": "keep me", "goal": "Must survive restarts.",
                                                 "auto_approve": True}).json()["project_id"]
        poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
        files = client.get(f"/api/projects/{pid}/artifacts").json()
        cookies, csrf = dict(client.cookies), client.headers["X-CSRF-Token"]

    second = build()
    with TestClient(create_app(second, run_agents=False)) as client:
        for k, v in cookies.items():
            client.cookies.set(k, v)
        client.headers["X-CSRF-Token"] = csrf
        assert client.get("/api/auth/me").json()["user"]["email"] == "restart@example.test"
        project = client.get(f"/api/projects/{pid}").json()
        assert project["state"] == "COMPLETED" and project["runs"][0]["goal"] == "Must survive restarts."
        assert [p["project_id"] for p in client.get("/api/projects").json()] == [pid]
        assert len(client.get(f"/api/projects/{pid}/artifacts").json()) == len(files) > 0
        history = client.get("/api/events", params={"project_id": pid}).json()
        assert any(e["event_type"] == "project.completed" for e in history)
    for s in (first, second):
        asyncio.run(delete_namespace(s.bus.namespace))


async def _wait(cond, timeout: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not await cond():
        if loop.time() > end:
            raise AssertionError("timeout")
        await asyncio.sleep(0.1)


async def test_manager_restart_recovers_from_postgres(infra, tmp_path) -> None:
    """Commit a plan, kill the Manager + publisher before anything is sent, start a NEW Manager process-equivalent
    over the same database: the outbox replays and the project completes. State survived in Postgres, not memory."""
    url, schema = infra
    ns = new_namespace()
    s = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "a"), llm=FakeLLM(),
                   plugins=discover(), config=CFG, persistence=persistence(url, schema))
    try:
        await s.start(with_agents=True, migrate=False)
        s.publisher.stop()
        assert s._publisher_task is not None
        s._publisher_task.cancel()
        m = s.manager
        pid = await m.create_project("restart")
        await m.submit_graph(pid, TaskGraph(project_id=pid, tasks=[
            PlanTask(id="T1", title="a", agent_capability="echo"),
            PlanTask(id="T2", title="b", agent_capability="echo", depends_on=["T1"])]), require_approval=False)
        assert await s.outbox.unpublished()
        await m.stop()

        p2 = persistence(url, schema)                       # brand-new connections = a restarted process
        m2 = Manager(bus=s.bus, store=p2.store, outbox=p2.outbox, registry=p2.registry, artifacts=s.artifacts,
                     contexts=p2.contexts, plugins=s.plugins, config=CFG.manager, inbox=InMemoryInboxStore())
        await m2.start(watchdog_interval_s=0.1)
        pub = OutboxPublisher(p2.outbox, s.bus)
        task = asyncio.create_task(pub.run_forever(0.05))

        async def done() -> bool:
            return (await m2.get_project(pid))["state"] == ProjectState.COMPLETED

        await _wait(done)
        pub.stop()
        task.cancel()
        await m2.stop()
        await p2.db.close()
    finally:
        await s.stop()
        await delete_namespace(ns)

"""Over the real stack (item 4.14): API -> Manager on PostgreSQL -> RabbitMQ -> DocIntelAgent / PlanningAgent with
``refine=true`` -> the refine adapters (Member 2/3 code untouched) -> traces, versions and events in Postgres; plus a
dead letter replayed as a new execution (item 4.18) and explained (4.16). Replay mode: no network, no keys, no
Ollama. Skipped (with the reason) when ``make infra-up`` has not run."""

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.llm import Gateway
from hmap.core.runtime.discovery import discover
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.system import HmapSystem
from tests.api.helpers import signed_in
from tests.core.bus.conftest import delete_namespace, make_rabbit_bus, new_namespace
from tests.e2e.test_full_stack import CFG, infra, persistence  # noqa: F401  (module fixture re-used)

pytestmark = pytest.mark.integration
PDF = REPO_ROOT / "samples" / "doc_intel" / "gold" / "docs" / "g07_messy" / "weather_dashboard.pdf"


@pytest.fixture
def client(infra: tuple[str, str], tmp_path: Any) -> Iterator[TestClient]:  # noqa: F811
    url, schema = infra
    ns = new_namespace()
    system = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"),
                        llm=Gateway(Settings(llm_mode="replay")), plugins=discover(), config=CFG,
                        persistence=persistence(url, schema))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c
    asyncio.run(delete_namespace(ns))


def poll(client: TestClient, url: str, pred: Any, timeout: float = 90.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout on {url}: {body}")


def test_refined_extraction_and_plan_over_rabbitmq_and_postgres(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "weather", "refine": True}).json()["project_id"]
    up = client.post(f"/api/projects/{pid}/documents",
                     files={"file": ("weather_dashboard.pdf", PDF.read_bytes(), "application/pdf")})
    assert up.status_code == 201
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    runs = poll(client, f"/api/refine/runs/{pid}", lambda rs: len(rs) == 2 and all(r["status"] == "stopped"
                                                                                  for r in rs))
    ex = next(r for r in runs if r["capability"] == "document.extract")
    assert ex["applied"] and ex["best_score"] > ex["base_score"]               # recorded judge + reviser answers
    rs = client.get(f"/api/doc_intel/requirements/{pid}").json()
    assert rs["artifact"]["version"] == 2
    events = poll(client, f"/api/events?project_id={pid}&limit=2000",
                  lambda es: sum(e["event_type"] == "refine.stopped" for e in es) == 2)
    assert any(e["event_type"] == "refine.iteration" for e in events)
    why = client.get(f"/api/ops/explain/{ex['task_id']}").json()                 # events + outbox from Postgres
    assert why["verdict"]["status"] == "completed" and why["messages"][0]["processed_by"]
    assert any(t["event_type"] == "task.completed" for t in why["timeline"])


def test_dead_letter_replay_over_rabbitmq_and_postgres(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "ops"}).json()["project_id"]
    tid = client.post(f"/api/projects/{pid}/tasks", json={
        "capability": "research.run", "objective": "fetch",
        "inputs": {"stub_fail": "TOOL_TRANSIENT", "stub_fail_times": 1 + CFG.manager.max_retries}}).json()["task_id"]
    poll(client, f"/api/tasks/{tid}", lambda t: t["state"] == "DEAD_LETTERED")
    assert [t["task_id"] for t in client.get("/api/ops/dlq").json()["tasks"]] == [tid]
    r = client.post(f"/api/ops/replay/{tid}", json={"reason": "fixed the source"})
    assert r.status_code == 200
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] == "COMPLETED")
    assert len(task["executions"]) == 2 + CFG.manager.max_retries and task["replays"] == 1
    why = client.get(f"/api/ops/explain/{tid}").json()
    assert any(e["event_type"] == "task.replayed" for e in why["timeline"])
    assert len(why["messages"]) == len(task["executions"])                      # one assignment per execution

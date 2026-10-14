"""Over the real stack (DoD): API -> Manager on PostgreSQL -> RabbitMQ -> DocIntelAgent -> PlanningAgent -> approval
-> stub steps in dependency order, with independent steps overlapping in time, then a replan that keeps the finished
work. Replay mode: no network, no keys, no Ollama. Skipped (with the reason) when ``make infra-up`` has not run."""

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
PDF = REPO_ROOT / "samples" / "doc_intel" / "gold" / "docs" / "g01_tcp_chat" / "tcp_chat_assignment.pdf"


@pytest.fixture
def client(infra: tuple[str, str], tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:  # noqa: F811
    monkeypatch.setenv("HMAP_STUB_DELAY_S", "0.4")          # placeholder steps take a moment, so overlap is visible
    url, schema = infra
    ns = new_namespace()
    system = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"),
                        llm=Gateway(Settings(llm_mode="replay")), plugins=discover(), config=CFG,
                        persistence=persistence(url, schema))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c
    asyncio.run(delete_namespace(ns))


def _poll(client: TestClient, url: str, pred: Any, timeout: float = 90.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout on {url}: {body}")


def test_pdf_to_plan_to_parallel_execution_and_replan_over_rabbitmq_and_postgres(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "TCP chat"}).json()["project_id"]
    up = client.post(f"/api/projects/{pid}/documents",
                     files={"file": ("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf")})
    assert up.status_code == 201
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    plan = client.get(f"/api/planning/plan/{pid}").json()
    assert plan["report"]["method"] == "llm"
    assert all(i["severity"] == "warning" for i in plan["report"]["issues"])
    graph = plan["graph"]
    assert client.post(f"/api/planning/plan/{pid}/approve",
                       json={"approved": True, "graph_version": 1}).status_code == 200
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")

    # dependency order: every step started after all its dependencies completed; and two steps overlapped
    tasks = {t["task_id"]: t for t in client.get(f"/api/projects/{pid}/tasks").json() if t["plan_task_id"]}
    # the event feed is filled from RabbitMQ and can trail the database by a moment: wait for every completion
    def all_completed(evs: list[dict[str, Any]]) -> bool:
        done = {e["aggregate_id"] for e in evs if e["event_type"] == "task.completed"}
        return set(tasks) <= done
    events = sorted(_poll(client, f"/api/events?project_id={pid}&limit=2000", all_completed, timeout=30.0),
                    key=lambda e: e["seq"])
    started: dict[str, int] = {}
    completed: dict[str, int] = {}
    running: set[str] = set()
    peak = 0
    for e in events:
        tid = e["aggregate_id"]
        if tid not in tasks:
            continue
        if e["event_type"] == "task.started":
            started[tid] = e["seq"]
            running.add(tid)
            peak = max(peak, len(running))
        elif e["event_type"] == "task.completed":
            completed[tid] = e["seq"]
            running.discard(tid)
    assert len(completed) == len(graph["tasks"]) and peak >= 2
    for tid, t in tasks.items():
        for dep in t["depends_on"]:
            assert completed[dep] < started[tid], (t["plan_task_id"], dep)
    assert any(e["event_type"] == "plan.approved" for e in events)

    # replan with feedback: everything finished is kept, the new version waits for approval
    assert client.post(f"/api/planning/plan/{pid}/replan", json={"feedback": "Do not use threads"}).status_code == 202
    _poll(client, f"/api/projects/{pid}", lambda p: p["graph_version"] == 2)
    after = client.get(f"/api/planning/plan/{pid}").json()
    finished = [t["id"] for t in graph["tasks"] if t["phase"] in ("research", "design", "implement", "test")]
    assert all(after["states"][tid] == "COMPLETED" for tid in finished)        # finished work is kept
    assert any(t["title"].startswith("Change request") for t in after["graph"]["tasks"])

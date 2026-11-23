"""Items 10.15-10.17 in every pre-commit (Member 10): the three golden scenarios on the whole platform in process —
every discovered plug-in real, the Manager's recovery slot on, the gateway in replay with an empty cache (so every
model call misses and each agent takes its no-model path). The full-quality runs with recorded model answers are
``scripts/demo_final.sh`` (replay) / ``--record`` (team keys); this test proves the wiring end to end.

1. TCP chat PDF -> requirements -> plan -> research -> verify -> code -> test -> docs -> review; the project settles
   (COMPLETED after a PASS, or REVIEWING with the stop reason);
2. the report assignment: no coding step; research, verify and docs ran; the review judged it;
3. a change request mid-run: replanned, finished steps kept (same task ids, never run again), the review checks it.
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.llm.gateway import Gateway
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import signed_in

ROOT = Path(__file__).resolve().parents[3]
PDF = ROOT / "samples" / "demo" / "tcp_chat_assignment.pdf"
ESSAY = ROOT / "samples" / "review" / "e2e" / "essay" / "assignment.md"
SETTLED = ("COMPLETED", "FAILED", "CANCELLED", "REVIEWING")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_CODING_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("HMAP_TESTING_SANDBOX", "local")
    monkeypatch.setenv("HMAP_RESEARCH_MODE", "cached")
    llm = Gateway(Settings(llm_mode="replay", llm_cache_dir=tmp_path / "empty_cache"))
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=llm,
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def _poll(client: TestClient, url: str, pred: Any, timeout: float = 240.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout on {url}: {body}")


def _project(client: TestClient, name: str, file: Path, media: str) -> str:
    pid: str = client.post("/api/projects", json={"name": name, "auto_approve": True}).json()["project_id"]
    r = client.post(f"/api/projects/{pid}/documents", files={"file": (file.name, file.read_bytes(), media)})
    assert r.status_code == 201, r.text
    return pid


def _settled(client: TestClient, pid: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    project = _poll(client, f"/api/projects/{pid}", lambda p: p["state"] in SETTLED)
    tasks = client.get(f"/api/projects/{pid}/tasks").json()
    review = client.get(f"/api/review/reports/{pid}").json()
    return project, tasks, review


def _ran(tasks: list[dict[str, Any]], cap: str) -> bool:
    return any(t["capability"] == cap and t["state"] == "COMPLETED" for t in tasks)


def _review_settles(project: dict[str, Any], review: dict[str, Any]) -> None:
    last = review["rounds"][-1]
    assert last["recommendation"] is not None
    if project["state"] == "COMPLETED":
        assert last["recommendation"] == "PASS"
    else:
        assert project["state"] == "REVIEWING" and last["stop_reason"], last


def test_tcp_chat_end_to_end(client: TestClient) -> None:
    caps = {c["capability"]: c["status"] for c in client.get("/api/agents/capabilities").json()}
    assert caps["review.final"] == "real" and caps["code.implement"] == "real"
    pid = _project(client, "TCP chat", PDF, "application/pdf")
    project, tasks, review = _settled(client, pid)
    for cap in ("document.extract", "plan.generate", "research.run", "verify.claims", "code.implement", "test.run",
                "docs.generate", "review.final"):
        assert _ran(tasks, cap), cap
    _review_settles(project, review)
    detail = client.get(f"/api/review/reports/{pid}/{review['rounds'][-1]['task_id']}").json()
    ids = {i["item"]["id"] for i in detail["items"]}
    assert {"R1", "C1", "D1", "E1"} <= ids                # requirements, constraints, deliverables, marks
    for video in (i for i in detail["items"] if "video" in i["item"]["text"].lower()):
        assert video["check"]["no_action"]                # a person's part: never revised (when extracted)


def test_report_assignment_end_to_end(client: TestClient) -> None:
    pid = _project(client, "Report", ESSAY, "text/markdown")
    project, tasks, review = _settled(client, pid)
    assert not any(t["capability"].startswith("code.") for t in tasks)
    for cap in ("document.extract", "plan.generate", "research.run", "verify.claims", "docs.generate",
                "review.final"):
        assert _ran(tasks, cap), cap
    _review_settles(project, review)


def test_change_request_mid_run_keeps_finished_work(client: TestClient) -> None:
    pid = _project(client, "TCP chat + change", PDF, "application/pdf")
    _poll(client, f"/api/projects/{pid}/tasks", lambda ts: any(t["capability"] == "code.implement" and
                                                               t["state"] == "COMPLETED" for t in ts))
    before = {t["task_id"] for t in client.get(f"/api/projects/{pid}/tasks").json()
              if t.get("plan_task_id") and t["state"] == "COMPLETED"}
    r = client.post(f"/api/planning/plan/{pid}/replan",
                    json={"feedback": "Do not use asyncio; use one thread per client instead."})
    assert r.status_code == 202, r.text
    project, tasks, review = _settled(client, pid)
    by_id = {t["task_id"]: t for t in tasks}
    assert _ran(tasks, "plan.replan")
    assert all(by_id[t]["state"] == "COMPLETED" and not by_id[t].get("replaced") for t in before)
    assert all(len([e for e in client.get(f"/api/tasks/{t}").json()["executions"]]) == 1 for t in before)
    _review_settles(project, review)
    detail = client.get(f"/api/review/reports/{pid}/{review['rounds'][-1]['task_id']}").json()
    assert any(i["item"]["kind"] == "change" for i in detail["items"])

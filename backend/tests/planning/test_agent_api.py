"""The agent on its own (3.8), the plug-in hooks, and the API through the real app (3.11): upload -> requirements ->
plan without manual steps, edits as versions, approval with versions, replanning, ``plan.approved``, ownership."""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.agents.planning.agent import LruCache, PlanningAgent, report_id
from hmap.agents.planning.decompose import DraftPlan
from hmap.agents.planning.model import PlanReport
from hmap.agents.planning.plugin import PLUGIN
from hmap.api.app import create_app
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts import TaskAssign
from hmap.core.contracts.capabilities import PLAN_GENERATE, PLAN_REPLAN
from hmap.core.contracts.domain import TaskGraph
from hmap.core.errors import HmapError
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.llm import FakeLLM, Gateway
from hmap.core.runtime.base import AgentContext
from hmap.core.runtime.discovery import validate_plugin
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

from .conftest import gold_rs, small_rs

PROJECT = "P-PLANNING"
PDF = REPO_ROOT / "samples" / "doc_intel" / "gold" / "docs" / "g01_tcp_chat" / "tcp_chat_assignment.pdf"


def test_plugin_shape() -> None:
    validate_plugin(PLUGIN)                                             # raises on a malformed plug-in
    assert PLUGIN.name == "planning" and PLUGIN.priority > 0 and "executor" in PLUGIN.provides
    assert PlanningAgent.capabilities == (PLAN_GENERATE, PLAN_REPLAN) and not PlanningAgent.is_stub
    assert {h.event_type for h in PLUGIN.manager_hooks} == {"task.completed", "approval.decided"}


async def _ctx(task: TaskAssign, store: Any, llm: Any) -> AgentContext:
    return AgentContext(task=task, agent_id="planner-1", llm=llm, artifacts=store, context=InMemoryContextStore(),
                        logger=None)


async def test_agent_returns_graph_then_report_and_is_idempotent() -> None:
    store = InMemoryArtifactStore()
    rs = small_rs(project_id=PROJECT)
    rs_ref = await store.put(rs.model_dump_json().encode(), project_id=PROJECT, artifact_type="requirement-set",
                             media_type="application/json", created_by="doc-intel")
    from hmap.agents.planning.decompose import rule_draft
    from hmap.agents.planning.skeleton import Part
    llm = FakeLLM().on_schema(DraftPlan, rule_draft(Part("p1", "", list(rs.requirements)), list(rs.requirements),
                                                     "software").model_dump_json())
    PlanningAgent.cache = LruCache()
    task = TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=PLAN_GENERATE,
                      objective="plan", acceptance_criteria=[], context_refs=[], project_id=PROJECT,
                      artifact_refs=[rs_ref])
    result = await PlanningAgent().handle(task, await _ctx(task, store, llm))
    graph_ref, report_ref = result.artifact_refs
    assert (graph_ref.artifact_type, report_ref.artifact_type) == ("task-graph", "plan-report")
    assert report_ref.artifact_id == report_id(graph_ref.artifact_id) and graph_ref.version == 1
    graph = TaskGraph.model_validate_json(await store.get(graph_ref, project_id=PROJECT))
    report = PlanReport.model_validate_json(await store.get(report_ref, project_id=PROJECT))
    assert graph.project_id == PROJECT and graph.version == 1
    assert report.requirement_set == {"artifact_id": rs_ref.artifact_id, "version": 1}
    assert result.summary and "steps" in result.summary
    # redelivery: same answer, no second model call
    again = await PlanningAgent().handle(task, await _ctx(task, store, llm))
    assert len(llm.calls) == 1 and again.outcome == "success"


async def test_agent_without_requirements_is_an_invalid_task() -> None:
    task = TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=PLAN_GENERATE,
                      objective="plan", acceptance_criteria=[], context_refs=[], project_id=PROJECT)
    with pytest.raises(HmapError) as exc:
        await PlanningAgent().handle(task, await _ctx(task, InMemoryArtifactStore(), FakeLLM()))
    assert not exc.value.retryable


async def test_agent_replan_writes_the_next_version_of_the_same_artifact() -> None:
    store = InMemoryArtifactStore()
    rs = gold_rs("tcp_chat").model_copy(update={"project_id": PROJECT})
    rs_ref = await store.put(rs.model_dump_json().encode(), project_id=PROJECT, artifact_type="requirement-set",
                             media_type="application/json", created_by="doc-intel")
    gen = TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=PLAN_GENERATE,
                     objective="plan", acceptance_criteria=[], context_refs=[], project_id=PROJECT,
                     artifact_refs=[rs_ref])
    first = await PlanningAgent().handle(gen, await _ctx(gen, store, None))
    graph_ref = first.artifact_refs[0]
    states = {"research": "COMPLETED", "verify": "COMPLETED"}
    task = TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=PLAN_REPLAN,
                      objective="replan", acceptance_criteria=[], context_refs=[], project_id=PROJECT,
                      artifact_refs=[graph_ref, rs_ref], inputs={"feedback": "Do not use threads", "states": states})
    result = await PlanningAgent().handle(task, await _ctx(task, store, None))
    new_ref, report_ref = result.artifact_refs
    assert new_ref.artifact_id == graph_ref.artifact_id and new_ref.version == 2 and report_ref.version == 2
    graph = TaskGraph.model_validate_json(await store.get(new_ref, project_id=PROJECT))
    assert graph.version == 2


# ---------------------------------------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=Gateway(Settings(llm_mode="replay")),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def _poll(client: TestClient, url: str, pred: Any, timeout: float = 20.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}: {body}")


def _events(client: TestClient, pid: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = client.get("/api/events", params={"project_id": pid}).json()
    return events


def test_upload_plan_edit_approve_replan_and_ownership(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "TCP chat"}).json()["project_id"]
    assert client.get(f"/api/planning/plan/{pid}").status_code == 404
    up = client.post(f"/api/projects/{pid}/documents",
                     files={"file": ("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf")})
    assert up.status_code == 201
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")

    plan = client.get(f"/api/planning/plan/{pid}").json()
    graph, report = plan["graph"], plan["report"]
    assert plan["artifact"]["version"] == 1 and plan["submitted_version"] == 1
    assert report["method"] == "llm" and set(graph["coverage_matrix"]) == {f"R{i}" for i in range(1, 9)}
    assert set(plan["states"]) == {t["id"] for t in graph["tasks"]} and set(plan["states"].values()) == {"CREATED"}
    assert plan["requirements"]["changed"] is False
    assert client.get(f"/api/planning/plan/{pid}/roadmap.md").text.startswith("# Plan")
    caps = client.get("/api/planning/capabilities").json()
    assert "plan.generate" not in caps["capabilities"] and caps["by_phase"]["review"] == ["review.final"]

    # edits: stale -> 409; a cycle -> 422 with the issue; a good edit -> version 2, approval needed again
    art = plan["artifact"]["artifact_id"]
    builds = [t for t in graph["tasks"] if t["phase"] == "implement"]
    cyclic = {**graph, "tasks": [dict(t, depends_on=[*t["depends_on"], "review"]) if t["id"] == builds[0]["id"]
                                 else t for t in graph["tasks"]]}
    r = client.put(f"/api/planning/plan/{pid}", json={"artifact_id": art, "base_version": 1, "graph": cyclic})
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["code"] == "cycle"
    edited = {**graph, "tasks": [dict(t, title="Accept many clients at once") if t["id"] == builds[0]["id"] else t
                                 for t in graph["tasks"]]}
    r = client.put(f"/api/planning/plan/{pid}", json={"artifact_id": art, "base_version": 1, "graph": edited})
    assert r.status_code == 200, r.text
    v2 = r.json()
    assert v2["artifact"]["version"] == 2 and v2["submitted_version"] == 2 and v2["report"]["origin"] == "edited"
    assert v2["report"]["author"].startswith("user:") and len(v2["versions"]) == 2
    assert client.put(f"/api/planning/plan/{pid}", json={"artifact_id": art, "base_version": 1,
                                                          "graph": edited}).status_code == 409
    project = client.get(f"/api/projects/{pid}").json()
    assert project["state"] == "AWAITING_APPROVAL"
    assert sorted(a["status"] for a in project["approvals"]) == ["pending", "rejected"]   # v1's request superseded

    # approval: rejecting needs a reason; deciding on the old version -> 409; then approve v2
    assert client.post(f"/api/planning/plan/{pid}/approve", json={"approved": False}).status_code == 422
    assert client.post(f"/api/planning/plan/{pid}/approve",
                       json={"approved": True, "graph_version": 1}).status_code == 409
    assert client.post(f"/api/planning/plan/{pid}/approve",
                       json={"approved": True, "graph_version": 2, "comment": "go"}).status_code == 200
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    approved = [e for e in _events(client, pid) if e["event_type"] == "plan.approved"]
    assert approved and approved[-1]["data"]["graph_version"] == 2
    assert approved[-1]["data"]["plan_ref"]["artifact_id"] == art

    # replan after completion: finished steps kept, a new version waits for approval
    r = client.post(f"/api/planning/plan/{pid}/replan", json={"feedback": "Do not use threads"})
    assert r.status_code == 202
    _poll(client, f"/api/planning/plan/{pid}", lambda p: p["artifact"]["version"] == 3)
    v3 = _poll(client, f"/api/projects/{pid}", lambda p: p["graph_version"] == 3)
    assert v3["state"] in ("AWAITING_APPROVAL", "EXECUTING", "COMPLETED")
    after = client.get(f"/api/planning/plan/{pid}").json()
    states = after["states"]
    work = [t["id"] for t in edited["tasks"] if t["phase"] in ("research", "design", "implement", "test")]
    assert work and all(states[tid] == "COMPLETED" for tid in work)               # finished work is kept
    new = [t for t in after["graph"]["tasks"] if t["id"] not in plan["states"]]
    assert any(t["title"].startswith("Change request") for t in new)               # the feedback became work
    assert any(t["phase"] == "review" and t["id"] != "review" for t in new)       # the review runs again
    assert all(states[t["id"]] == "CREATED" for t in new)

    # someone else sees nothing
    other = second_client(client)
    signed_in(other)
    for url in (f"/api/planning/plan/{pid}", f"/api/planning/plan/{pid}/roadmap.md"):
        assert other.get(url).status_code == 404
    assert other.put(f"/api/planning/plan/{pid}", json={"artifact_id": art, "base_version": 3,
                                                         "graph": edited}).status_code == 404
    assert other.post(f"/api/planning/plan/{pid}/approve", json={"approved": True}).status_code == 404
    assert other.post(f"/api/planning/plan/{pid}/replan", json={}).status_code == 404


def test_auto_approved_plan_also_announces_plan_approved(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "auto", "auto_approve": True}).json()["project_id"]
    client.post(f"/api/projects/{pid}/documents",
                files={"file": ("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf")})
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    approved = [e for e in _events(client, pid) if e["event_type"] == "plan.approved"]
    assert len(approved) == 1 and approved[0]["data"]["auto"] is True


def test_parallel_steps_overlap_in_the_event_log(client: TestClient) -> None:
    """DoD: two independent steps are running at the same time (from task.started / task.completed events)."""
    pid = client.post("/api/projects", json={"name": "parallel", "auto_approve": True}).json()["project_id"]
    client.post(f"/api/projects/{pid}/documents",
                files={"file": ("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf")})
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    events = _events(client, pid)
    running: set[str] = set()
    peak = 0
    plan_tasks = {t["task_id"] for t in client.get(f"/api/projects/{pid}/tasks").json() if t["plan_task_id"]}
    for e in sorted(events, key=lambda e: e["seq"]):
        if e["aggregate_id"] not in plan_tasks:
            continue
        if e["event_type"] == "task.started":
            running.add(e["aggregate_id"])
            peak = max(peak, len(running))
        elif e["event_type"] in ("task.completed", "task.failed", "task.cancelled"):
            running.discard(e["aggregate_id"])
    assert peak >= 2


def test_without_the_planning_plugin_the_stub_planner_and_naive_executor_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Spec 3.9: HMAP_PLUGINS without `planning` -> the Sprint-1 stub planner and the naive executor still finish."""
    from hmap.core.runtime.discovery import discover
    from hmap.manager import NaiveTopologicalExecutor

    plugins = discover({"stubs", "pipeline", "doc_intel"})
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=Gateway(Settings(llm_mode="replay")),
                                  plugins=plugins, config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    assert type(system.manager.executor) is NaiveTopologicalExecutor
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        caps = {x["capability"]: x["status"] for x in _poll(c, "/api/agents/capabilities", lambda b: len(b) >= 8)}
        assert caps["plan.generate"] == "stub"
        pid = c.post("/api/projects", json={"name": "no planner", "auto_approve": True}).json()["project_id"]
        c.post(f"/api/projects/{pid}/documents",
               files={"file": ("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf")})
        _poll(c, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
        assert c.get(f"/api/planning/plan/{pid}").status_code == 404      # the plan API is not mounted

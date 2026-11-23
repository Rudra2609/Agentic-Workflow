"""Items 10.7 / 10.8 / 10.9: the closed loop on the in-memory platform — Manager + the ``recovery`` slot + the real
review agent, with scripted code / test / docs agents (the world they report is set per test).

1. guide §32: the multi-client test fails in ``server.py`` -> review REVISE -> only the server step is revised, the
   test and docs steps re-run, the client step is not -> review round 1 PASS -> project COMPLETED;
2. a fix that never helps -> plateau -> ESCALATE -> the project waits in REVIEWING -> a person accepts with notes
   (API) -> COMPLETED; the API lists both rounds and the decision;
3. a person overrides the failing items -> the report gets a new version and the project completes;
4. ``review.completed`` is emitted for every review; the stub stands down.
"""

import io
import json
import tarfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from hmap.agents.review.plugin import PLUGIN as REVIEW
from hmap.api.app import create_app
from hmap.core.contracts import (
    CodeChangeSet,
    DocBundle,
    RequirementSet,
    TaskAssign,
    TaskGraph,
    TaskResult,
    TestReport,
)
from hmap.core.contracts.capabilities import CODE_IMPLEMENT, CODE_REVISE, DOCS_GENERATE, DOCS_UPDATE, TEST_RUN
from hmap.core.contracts.domain import AccuracyReport, PlanTask, StageResult, TestFailure
from hmap.core.llm import FakeLLM
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

WORLD: dict[str, Any] = {}       # {"broken": "server.py" | None, "fixable": bool}


def _tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"print('hi')\n"
        info = tarfile.TarInfo("server.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Coder(BaseAgent):
    name = "fake-coder"
    capabilities: ClassVar[tuple[str, ...]] = (CODE_IMPLEMENT, CODE_REVISE)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        if WORLD.get("fail_once") and task.capability == CODE_IMPLEMENT and "server" in task.objective.lower():
            WORLD["fail_once"] = False
            return ctx.result([], summary="the model returned nothing usable", outcome="failure")
        text = " ".join([task.objective, *task.acceptance_criteria])
        f = "server.py" if "server" in text.lower() else "client.py"
        if task.capability == CODE_REVISE and WORLD.get("fixable", True):
            await ctx.put_json({"fixed": True}, artifact_type="fake-fix", artifact_id=f"fix-{f}")
        ws = await ctx.artifacts.put(_tar(), project_id=ctx.project_id, artifact_type="workspace",
                                     media_type="application/gzip", created_by=ctx.agent_id,
                                     artifact_id=f"ws-{task.task_id}")
        cs = CodeChangeSet(task_id=task.task_id, workspace_ref=ws, files_changed=[f],
                           notes="Production ready, fully concurrent, every edge case handled.")
        ref = await ctx.put_json(cs, artifact_type="code-change-set", artifact_id=f"cs-{task.task_id}")
        return ctx.result([ref], summary=f"wrote {f}")


class Tester(BaseAgent):
    name = "fake-tester"
    capabilities: ClassVar[tuple[str, ...]] = (TEST_RUN,)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        broken = WORLD.get("broken")
        fixed = broken and await ctx.artifacts.latest(f"fix-{broken}", project_id=ctx.project_id) is not None
        passed = not broken or bool(fixed)
        fails = [] if passed else [TestFailure(category="ASSERTION", file=broken,
                                               message="client 2 never receives the broadcast")]
        rep = TestReport(task_id=task.task_id, stages={"unit": StageResult(status="passed" if passed else "failed")},
                         failures=fails, passed=passed)
        ref = await ctx.put_json(rep, artifact_type="test-report", artifact_id=f"tr-{task.task_id}")
        loop = task.inputs.get("loop") or {}
        tt = await ctx.put_json({"loop": {"round": loop.get("round", 0)}, "failures": [f.model_dump() for f in fails],
                                 "coding_task_id": (task.dependencies or [None])[0]},
                                artifact_type="testing-trace", artifact_id=f"tt-{task.task_id}")
        return ctx.result([ref, tt], summary="passed" if passed else "failed")


class Docs(BaseAgent):
    name = "fake-docs"
    capabilities: ClassVar[tuple[str, ...]] = (DOCS_GENERATE, DOCS_UPDATE)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        readme = await ctx.put_json({"md": "# Chat"}, artifact_type="doc-readme", artifact_id=f"drd-{task.task_id}")
        b = DocBundle(task_id=task.task_id, readme_ref=readme, accuracy_report=AccuracyReport(grounded_pct=100))
        ref = await ctx.put_json(b, artifact_type="doc-bundle", artifact_id=f"db-{task.task_id}")
        return ctx.result([ref], summary="docs")


FAKES = Plugin(name="fakes", agents=[Coder, Tester, Docs], priority=200)
DONE = ("COMPLETED", "FAILED", "CANCELLED", "REVIEWING")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_REVIEW_MAX_ROUNDS", "3")
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=FakeLLM(default=None),
                                  plugins=[REVIEW, FAKES],
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def _call(client: TestClient, fn: Any) -> Any:
    return client.portal.call(fn)  # type: ignore[union-attr]


def _poll(client: TestClient, url: str, pred: Any, timeout: float = 30.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}: {body}")


def _start(client: TestClient) -> tuple[str, HmapSystem]:
    system: HmapSystem = client.app.state.system  # type: ignore[attr-defined]
    pid = client.post("/api/projects", json={"name": "chat"}).json()["project_id"]
    src = {"doc_id": "doc-1"}
    rs = RequirementSet.model_validate({
        "project_id": pid, "requirements": [
            {"id": "R1", "text": "The server handles several clients at the same time.", "source_ref": src},
            {"id": "R2", "text": "Messages are broadcast to every connected client.", "source_ref": src},
            {"id": "R3", "text": "/quit disconnects the client cleanly.", "source_ref": src}],
        "deliverables": [{"id": "D1", "name": "README with run instructions"}]})
    graph = TaskGraph(project_id=pid, tasks=[
        PlanTask(id="T-srv", title="Write the server", agent_capability=CODE_IMPLEMENT, requirement_ids=["R1", "R2"]),
        PlanTask(id="T-cli", title="Write the client", agent_capability=CODE_IMPLEMENT, requirement_ids=["R3"]),
        PlanTask(id="T-test", title="Test the chat", agent_capability=TEST_RUN, depends_on=["T-srv", "T-cli"],
                 requirement_ids=["R1", "R2", "R3"], phase="test"),
        PlanTask(id="T-docs", title="Write the README", agent_capability=DOCS_GENERATE, depends_on=["T-test"],
                 phase="document"),
        PlanTask(id="T-rev", title="Final review", agent_capability="review.final", depends_on=["T-docs"],
                 phase="review")],
        coverage_matrix={"R1": ["T-srv", "T-test"], "R2": ["T-srv", "T-test"], "R3": ["T-cli", "T-test"],
                         "D1": ["T-docs"]})

    async def go() -> None:
        for obj, typ in ((rs, "requirement-set"), (graph, "task-graph")):
            await system.artifacts.put(obj.model_dump_json().encode(), project_id=pid, artifact_type=typ,
                                       media_type="application/json", created_by="test")
        await system.manager.submit_graph(pid, graph, require_approval=False)
    _call(client, go)
    return pid, system


def _tasks(client: TestClient, pid: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = _call(client, lambda: client.app.state.system.manager.list_tasks(pid))  # type: ignore[attr-defined]
    return sorted(out, key=lambda t: str(t["created_at"]))


def test_multi_client_failure_is_revised_and_passes(client: TestClient) -> None:
    WORLD.clear()
    WORLD.update(broken="server.py", fixable=True)
    pid, _ = _start(client)
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] in DONE)
    body = _poll(client, f"/api/review/reports/{pid}", lambda b: len(b["rounds"]) >= 2)
    project = client.get(f"/api/projects/{pid}").json()
    assert project["state"] == "COMPLETED", body
    first, second = body["rounds"][0], body["rounds"][-1]
    assert first["recommendation"] == "REVISE" and second["recommendation"] == "PASS"
    made = {t["capability"]: t for t in first["created_tasks"]}
    assert set(made) == {CODE_REVISE, TEST_RUN, DOCS_UPDATE, "review.final"}   # targeted: the client is not redone
    tasks = _tasks(client, pid)
    revise = next(t for t in tasks if t["capability"] == CODE_REVISE)
    srv = next(t for t in tasks if t.get("plan_task_id") == "T-srv")
    assert revise["parent_task_id"] == srv["task_id"]
    assert sum(1 for t in tasks if t["capability"] == CODE_IMPLEMENT) == 2          # no new client task
    detail = client.get(f"/api/review/reports/{pid}/{first['task_id']}").json()
    fails = {f["requirement_id"]: f for f in detail["report"]["failures"]}
    assert {"R1", "R2", "R3"} <= set(fails)
    assert {f["responsible_task_id"] for f in fails.values()} == {srv["task_id"]}   # R3 too: the file is server.py
    assert fails["R1"]["category"] == "INCORRECT"
    items = {i["item"]["id"]: i for i in detail["items"]}
    assert items["D1"]["verdict"] == "PASS"
    # the producer's confident note did not make anything pass
    assert items["R1"]["verdict"] == "FAIL"
    events = _poll(client, f"/api/events?project_id={pid}", lambda es: [e["data"]["outcome"] for e in es if
                                                                       e["event_type"] == "review.completed"][-1:]
                   == ["PASS"])          # the hook emits right after the run settles
    outcomes = [e["data"]["outcome"] for e in events if e["event_type"] == "review.completed"]
    assert outcomes[:1] == ["REVISE"] and outcomes[-1] == "PASS"
    assert any(e["event_type"] == "revision.requested" for e in events)


def test_stuck_fix_escalates_and_a_person_accepts(client: TestClient) -> None:
    WORLD.clear()
    WORLD.update(broken="server.py", fixable=False)
    pid, _ = _start(client)
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] in DONE, timeout=45)
    project = client.get(f"/api/projects/{pid}").json()
    assert project["state"] == "REVIEWING"
    body = client.get(f"/api/review/reports/{pid}").json()
    last = body["rounds"][-1]
    assert last["recommendation"] == "ESCALATE" and last["stop_reason"].startswith("plateau")
    assert len(body["rounds"]) == 2
    r = client.post(f"/api/review/reports/{pid}/{last['task_id']}/accept", json={"notes": "known limitation"})
    assert r.status_code == 200, r.text
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    again = client.get(f"/api/review/reports/{pid}").json()["rounds"][-1]
    assert again["decision"]["accepted"] is True and again["decision"]["history"][0]["notes"] == "known limitation"


def test_override_completes_and_foreign_user_gets_404(client: TestClient) -> None:
    WORLD.clear()
    WORLD.update(broken="server.py", fixable=False)
    pid, _ = _start(client)
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] in DONE, timeout=45)
    last = client.get(f"/api/review/reports/{pid}").json()["rounds"][-1]
    for rid in ("R1", "R2", "R3"):
        r = client.post(f"/api/review/reports/{pid}/{last['task_id']}/override",
                        json={"item_id": rid, "verdict": "PASS", "note": "checked by hand"})
        assert r.status_code == 200, r.text
    assert r.json()["report"]["recommendation"] == "PASS"
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    detail = client.get(f"/api/review/reports/{pid}/{last['task_id']}").json()
    assert {i["item"]["id"]: i["source"] for i in detail["items"]}["R1"] == "human"
    assert client.post(f"/api/review/reports/{pid}/{last['task_id']}/override",
                       json={"item_id": "R99", "verdict": "PASS"}).status_code == 404
    other = second_client(client)
    signed_in(other, name="Grace Hopper", email="grace@example.com")
    assert other.get(f"/api/review/reports/{pid}").status_code == 404


def test_request_changes_creates_a_revision(client: TestClient) -> None:
    WORLD.clear()
    WORLD.update(broken=None)
    pid, _ = _start(client)
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] in DONE)
    assert client.get(f"/api/projects/{pid}").json()["state"] == "COMPLETED"
    last = client.get(f"/api/review/reports/{pid}").json()["rounds"][-1]
    assert last["recommendation"] == "PASS"
    srv = next(t for t in _tasks(client, pid) if t.get("plan_task_id") == "T-srv")
    r = client.post(f"/api/review/reports/{pid}/{last['task_id']}/request-changes",
                    json={"text": "log every message to a file", "task_id": srv["task_id"]})
    assert r.status_code == 202, r.text
    _poll(client, f"/api/review/reports/{pid}", lambda b: len(b["rounds"]) >= 2 and
          b["rounds"][-1]["state"] == "COMPLETED")
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    revise = next(t for t in _tasks(client, pid) if t["capability"] == CODE_REVISE)
    assert "log every message" in json.dumps(revise["acceptance_criteria"])


def test_a_failed_step_is_rerun_and_the_project_completes(client: TestClient) -> None:
    WORLD.clear()
    WORLD.update(broken=None, fail_once=True)
    pid, _ = _start(client)
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] in DONE)
    assert client.get(f"/api/projects/{pid}").json()["state"] == "COMPLETED"
    tasks = _tasks(client, pid)
    failed = [t for t in tasks if t["state"] == "FAILED"]
    assert len(failed) == 1 and failed[0]["plan_task_id"] == "T-srv"
    rerun = next(t for t in tasks if (t.get("inputs") or {}).get("recovery", {}).get("action") == "rerun"
                 and t["capability"] == CODE_IMPLEMENT)
    assert rerun["parent_task_id"] == failed[0]["task_id"] and rerun["state"] == "COMPLETED"
    rounds = client.get(f"/api/review/reports/{pid}").json()["rounds"]
    assert [r["state"] for r in rounds][-1] == "COMPLETED" and rounds[-1]["recommendation"] == "PASS"

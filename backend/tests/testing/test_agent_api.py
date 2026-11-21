"""Items 8.9 / 8.10 / 8.14: the testing agent on the bus, the test -> code.revise -> test loop with Member 7's real
coding agent (scripted FakeLLM), the API, idempotency and the loop's stop rules. Local runner (no Docker)."""

import json
import logging
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.agents.coding.prompts import CodePlan
from hmap.agents.coding.workspace import Workspace, pack
from hmap.agents.testing.agent import TestingAgent
from hmap.agents.testing.model import FailureRecord, LoopState, TestingTrace
from hmap.agents.testing.refine_loop import decide, signature
from hmap.api.app import create_app
from hmap.core.contracts import ArtifactRef, TaskAssign, TestReport
from hmap.core.contracts.capabilities import CODE_IMPLEMENT, CODE_REVISE, TEST_RUN
from hmap.core.llm import FakeLLM
from hmap.core.runtime.base import AgentContext
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in
from tests.coding.conftest import BENCH, block

B3 = BENCH / "b3_median_even"
META = json.loads((B3 / "task.json").read_text())
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED")


def fake_llm() -> FakeLLM:
    """The first coding step only touches the README (the bug stays); a revision applies the real fix."""
    readme = (B3 / "starter" / "README.md").read_text().splitlines()[0] + "\n"

    def coder(call: Any) -> str:
        if "Requested changes" in call.messages[-1].content:
            return (B3 / "gold.edits").read_text()
        return block("README.md", readme, readme.rstrip("\n") + " (v2)\n")
    return FakeLLM(default=None).on_schema(CodePlan, CodePlan(summary="fix median", files_to_modify=["stats.py"]))\
        .on_role("coder", coder)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_CODING_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("HMAP_CODING_MAX_DEBUG_ROUNDS", "0")
    monkeypatch.setenv("HMAP_TESTING_SANDBOX", "local")
    monkeypatch.setenv("HMAP_TESTING_STAGE_TIMEOUT_S", "20")
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=fake_llm(),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def system_of(client: TestClient) -> HmapSystem:
    s: HmapSystem = client.app.state.system  # type: ignore[attr-defined]
    return s


def poll(client: TestClient, url: str, pred: Any, timeout: float = 90.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}: {body}")


def starter_with_tests() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(B3 / "starter", Path(tmp) / "ws")
        for f in (B3 / "hidden_tests").iterdir():
            shutil.copy(f, Path(tmp) / "ws" / f.name)
        return pack(Workspace(Path(tmp) / "ws"))


def call(client: TestClient, fn: Any) -> Any:
    return client.portal.call(fn)  # type: ignore[union-attr]


def get_json(client: TestClient, pid: str, ref: dict[str, Any]) -> Any:
    async def get() -> bytes:
        return await system_of(client).artifacts.get(ArtifactRef.model_validate(ref), project_id=pid)
    return json.loads(call(client, get))


def test_failed_tests_go_back_to_the_coding_agent_and_pass_after_the_fix(client: TestClient) -> None:
    system = system_of(client)
    pid = client.post("/api/projects", json={"name": "loop"}).json()["project_id"]

    async def put() -> ArtifactRef:
        return await system.artifacts.put(starter_with_tests(), project_id=pid, artifact_type="workspace",
                                          media_type="application/gzip", created_by="test", artifact_id="starter")
    start = call(client, put)

    async def implement() -> str:
        return await system.manager.create_task(pid, CODE_IMPLEMENT, META["objective"],
                                                acceptance_criteria=META["acceptance_criteria"],
                                                inputs={"workspace_ref": start.model_dump(mode="json")})
    code_id = call(client, implement)
    code = poll(client, f"/api/tasks/{code_id}", lambda t: t["state"] in DONE)
    refs = [ArtifactRef.model_validate(r) for r in code["executions"][-1]["result_refs"]]

    async def test_step() -> str:
        return await system.manager.create_task(pid, TEST_RUN, "Test the median fix",
                                                acceptance_criteria=META["acceptance_criteria"], artifact_refs=refs,
                                                depends_on=[code_id])
    test_id = call(client, test_step)
    first = poll(client, f"/api/tasks/{test_id}", lambda t: t["state"] in DONE)
    assert first["state"] == "COMPLETED" and first["executions"][-1]["outcome"] == "success"
    out = first["executions"][-1]["result_refs"]
    assert [r["artifact_type"] for r in out] == ["test-report", "test-log", "testing-trace"]
    report = TestReport.model_validate(get_json(client, pid, out[0]))
    assert not report.passed and report.task_id == test_id and report.exec_log_ref is not None
    assert report.stages["unit"].status == "failed" and report.stages["build"].status == "passed"
    assert any(f.category == "ASSERTION" and f.hint for f in report.failures)
    assert report.changeset_ref is not None and report.changeset_ref.artifact_id == f"ccs-{code_id}"

    # --- the loop: code.revise (parent = the coding step) + a new test.run that waits for it
    def loop_tasks(tasks: list[dict[str, Any]]) -> bool:
        return any(t["capability"] == TEST_RUN and t["task_id"] != test_id and t["state"] in DONE for t in tasks)
    tasks = poll(client, f"/api/projects/{pid}/tasks", loop_tasks)
    revise = next(t for t in tasks if t["capability"] == CODE_REVISE)
    retest = next(t for t in tasks if t["capability"] == TEST_RUN and t["task_id"] != test_id)
    assert revise["parent_task_id"] == code_id and revise["state"] == "COMPLETED"
    assert retest["depends_on"] == [revise["task_id"]] and retest["inputs"]["loop"]["round"] == 1
    assert retest["inputs"]["loop"]["origin_task_id"] == test_id
    retest = client.get(f"/api/tasks/{retest['task_id']}").json()
    second = TestReport.model_validate(get_json(client, pid, retest["executions"][-1]["result_refs"][0]))
    assert second.passed, second.failures
    time.sleep(0.5)
    tasks = client.get(f"/api/projects/{pid}/tasks").json()
    assert sum(t["capability"] == CODE_REVISE for t in tasks) == 1          # passed: the loop stopped
    events = client.get("/api/events", params={"project_id": pid, "limit": 500}).json()
    done = [e["data"] for e in events if e["event_type"] == "test.completed"]
    assert sorted(d["passed"] for d in done) == [False, True]
    assert {d["loop_round"] for d in done} == {0, 1}

    # --- API
    runs = client.get(f"/api/testing/runs/{pid}").json()
    assert {r["task_id"] for r in runs} == {test_id, retest["task_id"]}
    run = client.get(f"/api/testing/runs/{pid}/{test_id}").json()
    assert run["summary"]["passed"] is False and run["summary"]["backend"] == "local"
    assert [r["loop_round"] for r in run["loop"]] == [0, 1] and run["loop"][1]["passed"] is True
    assert run["report"]["passed"] is False and run["trace"]["failures"]
    log = client.get(f"/api/testing/runs/{pid}/{test_id}/log").text
    assert "=== [unit]" in log and "/work/" not in log
    assert client.get(f"/api/testing/runs/{pid}/nope").status_code == 404
    other = second_client(client)
    signed_in(other)
    assert other.get(f"/api/testing/runs/{pid}").status_code == 404
    assert other.post(f"/api/testing/runs/{pid}/{test_id}/rerun").status_code == 404
    r = client.post(f"/api/testing/runs/{pid}/{test_id}/rerun")
    assert r.status_code == 202, r.text
    again = poll(client, f"/api/tasks/{r.json()['task_id']}", lambda t: t["state"] in DONE)
    assert again["parent_task_id"] == test_id and "loop" not in again["inputs"]


# ------------------------------------------------------------------------------------------- the agent directly


def ctx_for(task: TaskAssign, store: InMemoryArtifactStore) -> AgentContext:
    return AgentContext(task=task, agent_id="testing-1", llm=FakeLLM(default=None), artifacts=store,
                        context=InMemoryContextStore(), logger=logging.getLogger("t"))


def assign(**kw: Any) -> TaskAssign:
    base: dict[str, Any] = {"task_id": "T1", "execution_id": "E1", "capability": TEST_RUN,
                            "objective": "test it", "acceptance_criteria": ["works"], "context_refs": [],
                            "project_id": "P"}
    return TaskAssign(**(base | kw))


async def test_nothing_to_test_is_partial_with_an_env_failure(tmp_path: Path) -> None:
    from hmap.core.config import Settings
    settings = Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path), "HMAP_TESTING_SANDBOX": "local"})
    store = InMemoryArtifactStore()
    res = await TestingAgent(settings).handle(assign(), ctx_for(assign(), store))
    assert res.outcome == "partial"
    report = TestReport.model_validate_json(await store.get(res.artifact_refs[0], project_id="P"))
    assert not report.passed and report.failures[0].category == "ENV"


async def test_redelivered_execution_returns_the_stored_result(tmp_path: Path) -> None:
    from hmap.core.config import Settings
    settings = Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path), "HMAP_TESTING_SANDBOX": "local"})
    store = InMemoryArtifactStore()
    ws = await store.put(starter_with_tests(), project_id="P", artifact_type="workspace",
                         media_type="application/gzip", created_by="t")
    task = assign(artifact_refs=[ws])
    agent = TestingAgent(settings)
    first = await agent.handle(task, ctx_for(task, store))
    second = await agent.handle(task, ctx_for(task, store))
    assert [r.version for r in second.artifact_refs] == [r.version for r in first.artifact_refs]
    assert "redelivered" in (second.summary or "")
    trace = TestingTrace.model_validate_json(await store.get(first.artifact_refs[-1], project_id="P"))
    assert trace.backend == "local" and "weaker" not in trace.isolation and trace.workspace_from.startswith("the cod")


# ----------------------------------------------------------------------------------------------- loop decisions


def trace_with(*failures: FailureRecord, passed: bool = False, ratio: float = 0.5, round_: int = 0,
               history: tuple[float, ...] = (), last: bool = False) -> TestingTrace:
    return TestingTrace(task_id="T", project_id="P", execution_id="E", failures=list(failures), passed=passed,
                        pass_ratio=ratio, coding_task_id="C",
                        loop=LoopState(round=round_, history=list(history),
                                       last_failures=signature(list(failures)) if last else []),
                        changeset_ref=ArtifactRef(artifact_id="ccs-C", version=1, artifact_type="code-change-set",
                                                  uri="mem://x", sha256="0" * 64, media_type="application/json",
                                                  size_bytes=1, created_by="t", created_at="2026-10-30T00:00:00Z",
                                                  access_scope="project"))


BUG = FailureRecord(stage="unit", category="ASSERTION", file="m.py", line=2, message="assert 1 == 2", hint="h")


@pytest.mark.parametrize(("trace", "enabled", "revise", "why"), [
    (trace_with(BUG), True, True, "actionable"),
    (trace_with(BUG), False, False, "off"),
    (trace_with(passed=True, ratio=1.0), True, False, "tests pass"),
    (trace_with(FailureRecord(stage="static", category="LINT", message="F401")), True, False, "no actionable"),
    (trace_with(BUG.model_copy(update={"generated": True})), True, False, "no actionable"),
    (trace_with(BUG.model_copy(update={"flaky": True})), True, False, "no actionable"),
    (trace_with(FailureRecord(stage="build", category="ENV", message="sandbox")), True, False, "no actionable"),
    (trace_with(BUG, round_=2, ratio=0.8, history=(0.2, 0.5)), True, False, "max_iters"),
    (trace_with(BUG, round_=1, ratio=0.5, history=(0.5,), last=True), True, False, "no_progress"),
    (trace_with(BUG, round_=1, ratio=0.5, history=(0.5,)), True, True, "actionable"),     # other failures now
    (trace_with(BUG, round_=1, ratio=0.7, history=(0.5,)), True, True, "actionable"),
])
def test_loop_decisions(trace: TestingTrace, enabled: bool, revise: bool, why: str) -> None:
    d = decide(trace, enabled=enabled, max_rounds=2)
    assert d.revise is revise and why in d.reason, d.reason
    if revise:
        assert d.required_changes[0] == "fix the ASSERTION failure at m.py:2: assert 1 == 2. Hint: h"

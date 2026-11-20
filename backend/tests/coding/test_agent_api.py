"""Item 7.9 (the agent on the bus: code.implement, code.revise, idempotency, failure injection, degraded mode),
item 7.14 (API) and plan D2 (the project workspace head), in memory with a scripted FakeLLM."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.agents.coding import package
from hmap.agents.coding.agent import CodingAgent
from hmap.agents.coding.model import CodingTrace
from hmap.agents.coding.prompts import CodePlan
from hmap.agents.coding.workspace import Workspace, files_from_tar, pack
from hmap.api.app import create_app
from hmap.core.contracts import ArtifactRef, CodeChangeSet, TaskAssign
from hmap.core.contracts.capabilities import CODE_IMPLEMENT, CODE_REVISE
from hmap.core.errors import HmapError
from hmap.core.llm import FakeLLM
from hmap.core.runtime.base import AgentContext
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in
from tests.coding.conftest import BENCH, block

B3 = BENCH / "b3_median_even"
GOLD_B3 = (B3 / "gold.edits").read_text()
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED")
TYPES = ["code-change-set", "workspace", "code-patch", "coding-trace"]


def fake_llm() -> FakeLLM:
    def coder(call: Any) -> str:
        prompt = call.messages[-1].content
        if "Requested changes" in prompt:   # the revision: add a docstring line
            return block("stats.py", "def median(values: list[float]) -> float:\n",
                         'def median(values: list[float]) -> float:\n    """Middle value; mean of the two middle '
                         'values for an even count."""\n')
        return GOLD_B3
    return FakeLLM(default=None).on_schema(CodePlan, CodePlan(summary="fix median", files_to_modify=["stats.py"]))\
        .on_role("coder", coder)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_CODING_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("HMAP_CODING_MAX_REVISIONS", "1")
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=fake_llm(),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def system_of(client: TestClient) -> HmapSystem:
    s: HmapSystem = client.app.state.system  # type: ignore[attr-defined]
    return s


def poll(client: TestClient, url: str, pred: Any, timeout: float = 60.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}: {body}")


def put_starter(client: TestClient, pid: str, task_dir: Path = B3) -> ArtifactRef:
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(task_dir / "starter", Path(tmp) / "ws")
        data = pack(Workspace(Path(tmp) / "ws"))

    async def put() -> ArtifactRef:
        return await system_of(client).artifacts.put(data, project_id=pid, artifact_type="workspace",
                                                     media_type="application/gzip", created_by="test",
                                                     artifact_id="starter")
    return client.portal.call(put)  # type: ignore[union-attr]


def create(client: TestClient, pid: str, capability: str = CODE_IMPLEMENT, **inputs: Any) -> str:
    meta = json.loads((B3 / "task.json").read_text())

    async def go() -> str:
        return await system_of(client).manager.create_task(pid, capability, meta["objective"],
                                                           acceptance_criteria=meta["acceptance_criteria"],
                                                           inputs=inputs or None)
    return client.portal.call(go)  # type: ignore[union-attr]


def get_bytes(client: TestClient, pid: str, ref: dict[str, Any]) -> bytes:
    async def get() -> bytes:
        return await system_of(client).artifacts.get(ArtifactRef.model_validate(ref), project_id=pid)
    return client.portal.call(get)  # type: ignore[union-attr]


def hidden_pass(files: dict[str, str], task_dir: Path = B3) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in files.items():
            (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / rel).write_text(text)
        for f in (task_dir / "hidden_tests").iterdir():
            shutil.copy(f, Path(tmp) / f.name)
        return subprocess.run([sys.executable, "-m", "unittest", "discover", "-p", "test_*.py"], cwd=tmp,
                              capture_output=True, timeout=60).returncode == 0


def test_code_implement_on_the_bus_api_head_and_revision(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "coding"}).json()["project_id"]
    start = put_starter(client, pid)
    tid = create(client, pid, workspace_ref=start.model_dump(mode="json"))
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in DONE)
    assert task["state"] == "COMPLETED", task
    refs = task["executions"][-1]["result_refs"]
    assert [r["artifact_type"] for r in refs] == TYPES
    ccs = CodeChangeSet.model_validate_json(get_bytes(client, pid, refs[0]))
    assert ccs.task_id == tid and ccs.files_changed == ["stats.py"] and ccs.patch_ref is not None
    assert any(c.cmd.startswith("python -m py_compile") for c in ccs.commands_run)
    assert hidden_pass(files_from_tar(get_bytes(client, pid, refs[1])))

    events = client.get("/api/events", params={"project_id": pid, "limit": 500}).json()
    done = [e for e in events if e["event_type"] == "code.completed"]
    assert len(done) == 1 and done[0]["data"]["files_changed"] == ["stats.py"]
    assert done[0]["data"]["checks_passed"] is True

    # --- API
    runs = client.get(f"/api/coding/runs/{pid}").json()
    assert [r["task_id"] for r in runs] == [tid] and runs[0]["outcome"] == "success"
    run = client.get(f"/api/coding/runs/{pid}/{tid}").json()
    assert "+    if len(ordered) % 2:" in run["diff"] and run["trace"]["steps"][0]["kind"] == "plan"
    assert run["summary"]["updated_at"]
    assert client.get(f"/api/coding/runs/{pid}/{tid}/diff").text == run["diff"]
    listing = client.get(f"/api/coding/runs/{pid}/{tid}/files").json()["files"]
    assert {f["path"] for f in listing} >= {"stats.py", "report.py"}
    assert "% 2" in client.get(f"/api/coding/runs/{pid}/{tid}/files", params={"path": "stats.py"}).json()["text"]
    for bad in ("../../etc/passwd", "/etc/passwd", "a/../../x"):
        assert client.get(f"/api/coding/runs/{pid}/{tid}/files", params={"path": bad}).status_code == 400
    assert client.get(f"/api/coding/runs/{pid}/{tid}/files", params={"path": "nope.py"}).status_code == 404
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/coding/runs/{pid}/{tid}/workspace.zip").content))
    assert any(n.endswith("/stats.py") for n in z.namelist())
    head = client.get(f"/api/coding/heads/{pid}").json()
    assert head["version"] == 1 and any(f["path"] == "stats.py" for f in head["files"])
    assert client.get(f"/api/coding/runs/{pid}/nope").status_code == 404

    # --- someone else's project is invisible
    other = second_client(client)
    signed_in(other)
    assert other.get(f"/api/coding/runs/{pid}").status_code == 404
    assert other.post(f"/api/coding/runs/{pid}/{tid}/revise", json={"required_changes": ["x"]}).status_code == 404

    # --- "Request changes" -> code.revise, starting from the head; one round allowed (HMAP_CODING_MAX_REVISIONS=1)
    r = client.post(f"/api/coding/runs/{pid}/{tid}/revise", json={"required_changes": ["document median"]})
    assert r.status_code == 202, r.text
    rid = r.json()["task_id"]
    rev = poll(client, f"/api/tasks/{rid}", lambda t: t["state"] in DONE)
    assert rev["state"] == "COMPLETED" and rev["capability"] == CODE_REVISE
    rrefs = rev["executions"][-1]["result_refs"]
    trace = CodingTrace.model_validate_json(get_bytes(client, pid, rrefs[3]))
    assert trace.base == "head" and trace.revision_round == 1 and trace.original_task_id == tid
    tree = files_from_tar(get_bytes(client, pid, rrefs[1]))
    assert '"""Middle value' in tree["stats.py"] and "% 2" in tree["stats.py"]       # both changes in the tree
    patch = get_bytes(client, pid, rrefs[2]).decode()
    added = [ln for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    assert any("Middle value" in ln for ln in added) and not any("% 2" in ln for ln in added)   # only this diff
    assert client.get(f"/api/coding/heads/{pid}").json()["version"] == 2
    assert client.get(f"/api/coding/runs/{pid}/{tid}").json()["revisions"][0]["task_id"] == rid
    again = client.post(f"/api/coding/runs/{pid}/{rid}/revise", json={"required_changes": ["more"]})
    assert again.status_code == 409 and "limit" in again.json()["detail"]


def test_a_greenfield_step_without_a_model_still_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAP_CODING_WORK_DIR", str(tmp_path / "work"))
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=FakeLLM(default=None),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        pid = c.post("/api/projects", json={"name": "green"}).json()["project_id"]

        async def go() -> str:
            return await system.manager.create_task(pid, CODE_IMPLEMENT, "Set up the skeleton of a TCP chat server "
                                                    "that serves many clients", acceptance_criteria=["it runs"])
        tid = c.portal.call(go)  # type: ignore[union-attr]
        task = poll(c, f"/api/tasks/{tid}", lambda t: t["state"] in DONE)
        assert task["state"] == "COMPLETED" and task["executions"][-1]["outcome"] == "partial"
        run = c.get(f"/api/coding/runs/{pid}/{tid}").json()
        assert run["summary"]["template"] == "tcp_server_client" and run["summary"]["stop_reason"] == "no_model"
        assert "NOT DONE" in run["changeset"]["notes"]


# ------------------------------------------------------------------------------------------- the agent directly


def ctx_for(task: TaskAssign, store: InMemoryArtifactStore, llm: FakeLLM) -> AgentContext:
    import logging
    return AgentContext(task=task, agent_id="coding-1", llm=llm, artifacts=store, context=InMemoryContextStore(),
                        logger=logging.getLogger("t"))


async def test_redelivered_execution_returns_the_stored_result(tmp_path: Path, settings: Any) -> None:
    store = InMemoryArtifactStore()
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(B3 / "starter", Path(tmp) / "ws")
        start = await store.put(pack(Workspace(Path(tmp) / "ws")), project_id="P", artifact_type="workspace",
                                media_type="application/gzip", created_by="t")
    task = TaskAssign(task_id="T1", execution_id="E1", capability=CODE_IMPLEMENT, objective="fix median",
                      acceptance_criteria=["median([1, 2, 3, 4]) == 2.5"], context_refs=[], project_id="P",
                      inputs={"workspace_ref": start.model_dump(mode="json")})
    fake = fake_llm()
    agent = CodingAgent(settings)
    first = await agent.handle(task, ctx_for(task, store, fake))
    calls = len(fake.calls)
    second = await agent.handle(task, ctx_for(task, store, fake))
    assert [r.version for r in second.artifact_refs] == [r.version for r in first.artifact_refs]
    assert len(fake.calls) == calls and "redelivered" in (second.summary or "")
    retry = task.model_copy(update={"execution_id": "E2"})          # a new execution runs again
    third = await agent.handle(retry, ctx_for(retry, store, fake))
    assert third.artifact_refs[0].version == 2


async def test_failure_injection_is_honoured(settings: Any) -> None:
    task = TaskAssign(task_id="TF", execution_id="E1", capability=CODE_IMPLEMENT, objective="x",
                      acceptance_criteria=[], context_refs=[], project_id="P",
                      inputs={"stub_fail": "TOOL_TRANSIENT", "stub_fail_times": 1})
    with pytest.raises(HmapError):
        await CodingAgent(settings).handle(task, ctx_for(task, InMemoryArtifactStore(), fake_llm()))


async def test_a_moved_head_is_merged(tmp_path: Path, settings: Any) -> None:
    """Two parts start from the same head; the second re-applies its change on the head the first one moved."""
    store = InMemoryArtifactStore()
    fake = FakeLLM()
    t1 = TaskAssign(task_id="A", execution_id="E", capability=CODE_IMPLEMENT, objective="a", acceptance_criteria=[],
                    context_refs=[], project_id="P")
    ctx = ctx_for(t1, store, fake)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "ws"
        root.mkdir()
        (root / "a.py").write_text("A = 1\n")
        (root / "b.py").write_text("B = 1\n")
        await store.put(pack(Workspace(root)), project_id="P", artifact_type="workspace-head",
                        media_type="application/gzip", created_by="t", artifact_id="wsh-P")
    for name in ("w1", "w2"):
        (tmp_path / name).mkdir()
    ws1, ws2 = Workspace(tmp_path / "w1"), Workspace(tmp_path / "w2")
    base1 = await package.load_base(t1, ctx, ws1)
    base2 = await package.load_base(t1.model_copy(update={"task_id": "B"}), ctx, ws2)
    ws1.write("a.py", "A = 2\n")
    ws2.write("b.py", "B = 2\n")
    trace = CodingTrace(task_id="A", project_id="P", capability=CODE_IMPLEMENT)
    s1 = await package.store(t1, ctx, ws1, trace, base1)
    s2 = await package.store(t1.model_copy(update={"task_id": "B"}), ctx, ws2,
                             CodingTrace(task_id="B", project_id="P", capability=CODE_IMPLEMENT), base2)
    assert s1.conflicts == [] and s2.conflicts == []
    head = await store.latest("wsh-P", project_id="P")
    assert head is not None and head.version == 3
    assert files_from_tar(await store.get(head, project_id="P")) == {"a.py": "A = 2\n", "b.py": "B = 2\n"}
    assert s2.changeset.files_changed == ["b.py"]


async def test_code_revise_fixes_a_seeded_failing_change_from_a_test_report(tmp_path: Path, settings: Any) -> None:
    """DoD: the revision loop on a seeded failing change. The input is what Member 8 will send: a TestReport."""
    from hmap.agents.coding.revise import revision_inputs
    from hmap.core.contracts.domain import StageResult, TestFailure, TestReport

    store = InMemoryArtifactStore()
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(B3 / "starter", Path(tmp) / "ws")                 # the seeded failing change
        head = await store.put(pack(Workspace(Path(tmp) / "ws")), project_id="P", artifact_type="workspace-head",
                               media_type="application/gzip", created_by="t", artifact_id="wsh-P")
    report = TestReport(task_id="T-ORIG", stages={"unit": StageResult(status="failed")}, passed=False,
                        failures=[TestFailure(category="ASSERTION", file="stats.py", line=15,
                                              message="median([1, 2, 3, 4]) returned 3, expected 2.5",
                                              hint="even count: average the two middle values")])
    rep_ref = await store.put(report.model_dump_json().encode(), project_id="P", artifact_type="test-report",
                              media_type="application/json", created_by="testing")
    task = TaskAssign(task_id="T-REV", execution_id="E1", capability=CODE_REVISE, objective="Fix what the tests found",
                      acceptance_criteria=["the unit tests pass"], context_refs=[], project_id="P",
                      artifact_refs=[rep_ref],
                      inputs=revision_inputs(head, required_changes=[], original_task_id="T-ORIG"))
    fake = FakeLLM(default=None).on_schema(CodePlan, CodePlan(summary="fix median", files_to_modify=["stats.py"]))\
        .on_role("coder", GOLD_B3)
    result = await CodingAgent(settings).handle(task, ctx_for(task, store, fake))
    assert result.outcome == "success"
    plan_prompt = fake.calls[0].messages[1].content
    assert "Reported failures" in plan_prompt and "average the two middle values" in plan_prompt
    trace = CodingTrace.model_validate_json(await store.get(result.artifact_refs[3], project_id="P"))
    assert trace.capability == CODE_REVISE and trace.base == "head" and trace.files_changed == ["stats.py"]
    assert hidden_pass(files_from_tar(await store.get(result.artifact_refs[1], project_id="P")))

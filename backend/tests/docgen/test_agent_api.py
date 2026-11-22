"""Items 9.9 / 9.10 / 9.13: the documentation agent on the bus (docs.completed, the API, ownership), the
code.completed -> docs.update hook, docs.update regenerating only what changed, document mode, degraded mode,
idempotency and the refine loop removing a model's false claim."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.agents.docgen import readme
from hmap.agents.docgen.agent import DocAgent
from hmap.agents.docgen.hooks import on_code_completed
from hmap.agents.docgen.model import Accuracy, DocgenTrace
from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, DocBundle, DomainEvent
from hmap.core.contracts.capabilities import DOCS_GENERATE, DOCS_UPDATE
from hmap.core.llm import FakeLLM
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in
from tests.docgen.conftest import assign, ctx_for, repo_files, tar_of
from tests.docgen.test_generators import _research, _rs

DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_CODING_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("HMAP_TESTING_SANDBOX", "local")
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=FakeLLM(default=None),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def system_of(client: TestClient) -> HmapSystem:
    s: HmapSystem = client.app.state.system  # type: ignore[attr-defined]
    return s


def call(client: TestClient, fn: Any) -> Any:
    return client.portal.call(fn)  # type: ignore[union-attr]


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


def test_docs_on_the_bus_api_and_the_update_hook(client: TestClient) -> None:
    system = system_of(client)
    pid = client.post("/api/projects", json={"name": "docs"}).json()["project_id"]

    async def put() -> ArtifactRef:
        return await system.artifacts.put(tar_of(repo_files("todo_api")), project_id=pid, artifact_type="workspace",
                                          media_type="application/gzip", created_by="test",
                                          artifact_id=f"wsh-{pid}")
    head = call(client, put)

    async def create() -> str:
        return await system.manager.create_task(pid, DOCS_GENERATE, "Write the README and API docs",
                                                acceptance_criteria=["docs exist"])
    tid = call(client, create)
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in DONE)
    exe = task["executions"][-1]
    assert task["state"] == "COMPLETED" and exe["outcome"] == "success", exe
    types = [r["artifact_type"] for r in exe["result_refs"]]
    assert types[0] == "doc-bundle" and types[-1] == "docgen-trace"
    assert {"doc-readme", "doc-api", "doc-architecture", "doc-summaries", "doc-report", "doc-accuracy",
            "docgen-facts"} <= set(types)

    async def get(ref: dict[str, Any]) -> bytes:
        return await system.artifacts.get(ArtifactRef.model_validate(ref), project_id=pid)
    bundle = DocBundle.model_validate_json(call(client, lambda: get(exe["result_refs"][0])))
    assert bundle.task_id == tid and bundle.accuracy_report.grounded_pct == 100.0
    assert bundle.accuracy_report.examples_verified >= 1          # the README's pytest ran in the sandbox
    events = poll(client, f"/api/events?project_id={pid}&limit=500",
                  lambda es: any(e["event_type"] == "docs.completed" for e in es))
    done = [e["data"] for e in events if e["event_type"] == "docs.completed"]
    assert done and done[0]["task_id"] == tid and done[0]["mode"] == "software" and done[0]["grounded_pct"] == 100

    # --- API
    runs = client.get(f"/api/docgen/bundles/{pid}").json()
    assert [r["task_id"] for r in runs] == [tid] and runs[0]["degraded"] is True
    one = client.get(f"/api/docgen/bundles/{pid}/{tid}").json()
    assert set(one["documents"]) == {"readme", "api", "architecture", "summaries", "report"}
    assert one["graph"]["nodes"] and one["accuracy"]["checked"] > 20 and one["bundle"]["task_id"] == tid
    md = client.get(f"/api/docgen/bundles/{pid}/{tid}/files/api").text
    assert "GET /todos/{todo_id}" in md
    assert client.get(f"/api/docgen/bundles/{pid}/{tid}/files/nope").status_code == 404
    checked = client.post(f"/api/docgen/check/{pid}", json={"markdown": "Todos are cached in Redis on port 6379. "
                                                                        "The API runs on port 8000."}).json()
    bad = [c for c in checked["accuracy"]["claims"] if c["verdict"] == "ungrounded"]
    assert {c["text"] for c in bad} == {"Redis", "port 6379"}
    other = second_client(client)
    signed_in(other)
    assert other.get(f"/api/docgen/bundles/{pid}").status_code == 404
    assert other.post(f"/api/docgen/check/{pid}", json={"markdown": "x"}).status_code == 404

    # --- code.completed -> docs.update (documents exist, none pending)
    async def emit() -> None:
        await system.manager.emit(DomainEvent(event_type="code.completed", aggregate_id="C1", project_id=pid,
                                              correlation_id=pid, data={"task_id": "C1"}))
    call(client, emit)
    tasks = poll(client, f"/api/projects/{pid}/tasks",
                 lambda ts: any(t["capability"] == DOCS_UPDATE and t["state"] in DONE for t in ts))
    upd = next(t for t in tasks if t["capability"] == DOCS_UPDATE)
    assert upd["state"] == "COMPLETED" and upd["inputs"]["previous_bundle"]["artifact_id"] == f"dh-{pid}"
    detail = client.get(f"/api/docgen/bundles/{pid}/{upd['task_id']}").json()
    assert detail["trace"]["previous_bundle"] == tid and detail["trace"]["changed_sections"] == []
    assert head.artifact_id == f"wsh-{pid}"

    svg = client.get(f"/api/docgen/bundles/{pid}/{tid}/architecture.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and "<svg" in svg.text
    page = client.get(f"/api/docgen/bundles/{pid}/{tid}/site.html")
    assert page.status_code == 200 and "default-src 'none'" in page.headers["content-security-policy"]
    assert "attachment" in page.headers["content-disposition"] and "GET /todos/{todo_id}" in page.text
    assert client.get(f"/api/docgen/bundles/{pid}/{tid}/docstrings.diff").status_code == 404   # no model: no patch
    assert other.get(f"/api/docgen/bundles/{pid}/{tid}/site.html").status_code == 404
    r = client.post(f"/api/docgen/bundles/{pid}/{tid}/regenerate")
    assert r.status_code == 202, r.text
    again = poll(client, f"/api/tasks/{r.json()['task_id']}", lambda t: t["state"] in DONE)
    assert again["parent_task_id"] == tid and again["state"] == "COMPLETED"


class _Manager:
    def __init__(self, store: InMemoryArtifactStore, tasks: list[dict[str, Any]]) -> None:
        self.artifacts = store
        self.tasks = tasks
        self.created: list[tuple[str, str]] = []

    async def list_tasks(self, project_id: str) -> list[dict[str, Any]]:
        return self.tasks

    async def create_task(self, project_id: str, capability: str, objective: str, **kw: Any) -> str:
        self.created.append((capability, objective))
        return "T-new"


async def test_update_hook_waits_for_pending_docs_and_needs_existing_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryArtifactStore()
    ev = DomainEvent(event_type="code.completed", aggregate_id="C1", project_id="P", correlation_id="P",
                     data={"task_id": "C1"})
    m = _Manager(store, [])
    await on_code_completed.fn(ev, m)  # type: ignore[arg-type]
    assert m.created == []                                   # no documents yet
    await store.put(b"{}", project_id="P", artifact_type="doc-bundle", media_type="application/json",
                    created_by="t", artifact_id="dh-P")
    m.tasks = [{"task_id": "D", "capability": DOCS_GENERATE, "state": "READY"}]
    await on_code_completed.fn(ev, m)  # type: ignore[arg-type]
    assert m.created == []                                   # the plan's own docs step is still to come
    m.tasks = [{"task_id": "D", "capability": DOCS_GENERATE, "state": "COMPLETED"}]
    monkeypatch.setenv("HMAP_DOCGEN_AUTO_UPDATE", "false")
    await on_code_completed.fn(ev, m)  # type: ignore[arg-type]
    assert m.created == []
    monkeypatch.setenv("HMAP_DOCGEN_AUTO_UPDATE", "true")
    await on_code_completed.fn(ev, m)  # type: ignore[arg-type]
    assert m.created == [(DOCS_UPDATE, "Update the documentation after the code change")]


async def _run(store: InMemoryArtifactStore, settings: Settings, llm: Any = None, **kw: Any) -> tuple[Any, Any]:
    task = assign(**kw)
    res = await DocAgent(settings, backend=None).handle(task, ctx_for(task, store, llm))
    return task, res


async def _get(store: InMemoryArtifactStore, res: Any, artifact_type: str, model: Any = None) -> Any:
    ref = next(r for r in res.artifact_refs if r.artifact_type == artifact_type)
    data = await store.get(ref, project_id="P")
    return model.model_validate_json(data) if model else data.decode()


async def test_refine_loop_removes_a_false_claim_of_the_model(settings: Settings) -> None:
    store = InMemoryArtifactStore()
    ws = await store.put(tar_of(repo_files("todo_api")), project_id="P", artifact_type="workspace",
                         media_type="application/gzip", created_by="t", artifact_id="ws")
    fake = FakeLLM(default=None).on_schema(readme._Prose, readme._Prose(
        what="A small to-do HTTP API. Todos are cached in Redis for speed."))
    _, res = await _run(store, settings, fake, artifact_refs=[ws])
    md = await _get(store, res, "doc-readme")
    assert "A small to-do HTTP API." in md and "Redis" not in md
    acc = await _get(store, res, "doc-accuracy", Accuracy)
    assert [c.text for c in acc.removed] == ["Redis"] and acc.grounded_pct < 100
    bundle = await _get(store, res, "doc-bundle", DocBundle)
    assert any("Redis" in u for u in bundle.accuracy_report.ungrounded_claims)
    trace = await _get(store, res, "docgen-trace", DocgenTrace)
    assert trace.rounds >= 1 and any("deleted from readme" in n for n in trace.notes)
    assert not trace.degraded


async def test_idempotent_redelivery_and_nothing_to_document(settings: Settings) -> None:
    store = InMemoryArtifactStore()
    _, empty = await _run(store, settings)
    assert empty.outcome == "partial" and "nothing to document" in (empty.summary or "")
    ws = await store.put(tar_of(repo_files("tcp_chat")), project_id="P", artifact_type="workspace",
                         media_type="application/gzip", created_by="t", artifact_id="ws")
    _, first = await _run(store, settings, task_id="T2", artifact_refs=[ws])
    _, again = await _run(store, settings, task_id="T2", artifact_refs=[ws])
    assert "redelivered" in (again.summary or "")
    assert [r.artifact_id for r in again.artifact_refs] == [r.artifact_id for r in first.artifact_refs]


async def test_docs_update_regenerates_only_what_changed(settings: Settings) -> None:
    store = InMemoryArtifactStore()
    files = repo_files("todo_api")
    ws1 = await store.put(tar_of(files), project_id="P", artifact_type="workspace", media_type="application/gzip",
                          created_by="t", artifact_id="ws")
    await _run(store, settings, task_id="G1", artifact_refs=[ws1])
    changed = dict(files)
    changed["app.py"] = files["app.py"] + '\n\n@app.get("/stats")\ndef stats() -> dict[str, int]:\n    return {}\n'
    ws2 = await store.put(tar_of(changed), project_id="P", artifact_type="workspace", media_type="application/gzip",
                          created_by="t", artifact_id="ws")
    _, res = await _run(store, settings, task_id="U1", capability=DOCS_UPDATE, artifact_refs=[ws2])
    trace = await _get(store, res, "docgen-trace", DocgenTrace)
    assert trace.previous_bundle == "G1"
    assert {"api", "readme"} <= set(trace.changed_sections)
    assert "GET /stats" in await _get(store, res, "doc-api")
    assert "Added endpoints: `GET /stats`." in trace.changelog
    assert "## Changes since the last documentation" in await _get(store, res, "doc-report")


async def test_document_mode(settings: Settings) -> None:
    store = InMemoryArtifactStore()
    rr, vr = _research()
    refs = [await store.put(rr.model_dump_json().encode(), project_id="P", artifact_type="research-report",
                            media_type="application/json", created_by="t", artifact_id="rr"),
            await store.put(vr.model_dump_json().encode(), project_id="P", artifact_type="verification-report",
                            media_type="application/json", created_by="t", artifact_id="vr"),
            await store.put(_rs().model_dump_json().encode(), project_id="P", artifact_type="requirement-set",
                            media_type="application/json", created_by="t", artifact_id="rs")]
    _, res = await _run(store, settings, artifact_refs=refs, inputs={"phase": "document"})
    assert res.outcome == "success"
    md = await _get(store, res, "doc-report")
    assert md.startswith("# Project report") and "UDP" not in md
    trace = await _get(store, res, "docgen-trace", DocgenTrace)
    assert trace.mode == "document" and trace.step == "document" and trace.coverage
    bundle = await _get(store, res, "doc-bundle", DocBundle)
    assert bundle.report_sections_ref is not None and bundle.readme_ref is None
    assert json.loads(await _get(store, res, "doc-accuracy"))["grounded_pct"] == 100.0


async def test_code_supplied_with_the_task(settings: Settings) -> None:
    from hmap.agents.docgen.agent import supplied_files
    assert supplied_files({"a.py": "x", "/etc/passwd": "x", "../b.py": "x", "c.py": 3}) == {"a.py": "x"}
    store = InMemoryArtifactStore()
    _, res = await _run(store, settings, inputs={"files": repo_files("tcp_chat")})
    trace = await _get(store, res, "docgen-trace", DocgenTrace)
    assert res.outcome == "success" and trace.source == "6 file(s) supplied with the task"

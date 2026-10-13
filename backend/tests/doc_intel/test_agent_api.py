"""The agent on its own (item 2.8), the plug-in and its event hook, and the API through the real app (items 2.9 and
2.10): upload -> RequirementSet without manual steps, edits as new versions, ownership, page images."""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.agents.doc_intel.agent import DocIntelAgent, LruCache, document_name
from hmap.agents.doc_intel.extract.llm import ChunkExtraction, ExtractedItem
from hmap.agents.doc_intel.model import DocumentModel
from hmap.agents.doc_intel.plugin import PLUGIN, announce_requirements
from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.contracts import DomainEvent, TaskAssign
from hmap.core.contracts.capabilities import DOCUMENT_EXTRACT
from hmap.core.contracts.domain import RequirementSet
from hmap.core.errors import HmapError
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.llm import FakeLLM, Gateway
from hmap.core.runtime.base import AgentContext
from hmap.core.runtime.discovery import validate_plugin
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

from .conftest import GOLD

PROJECT = "P-DOCINTEL"
PDF = GOLD / "docs" / "g01_tcp_chat" / "tcp_chat_assignment.pdf"


def replay() -> Gateway:
    return Gateway(Settings(llm_mode="replay"))


async def _run_agent(files: list[tuple[str, bytes, str, str | None]], *, with_meta: bool = True,
                     llm: Any = None, task: TaskAssign | None = None, store: Any = None
                     ) -> tuple[Any, AgentContext, list[tuple[int, str]]]:
    store = store or InMemoryArtifactStore()
    refs, docs = [], []
    for name, data, media, folder in files:
        ref = await store.put(data, project_id=PROJECT, artifact_type="document", media_type=media, created_by="user")
        refs.append(ref)
        docs.append({"artifact_id": ref.artifact_id, "name": name, "folder": folder,
                     "path": f"{folder}/{name}" if folder else name})
    progress: list[tuple[int, str]] = []

    async def record(pct: int, summary: str) -> None:
        progress.append((pct, summary))

    task = task or TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=DOCUMENT_EXTRACT,
                              objective="extract", acceptance_criteria=[], context_refs=[], project_id=PROJECT,
                              artifact_refs=refs, inputs={"documents": docs} if with_meta else {})
    ctx = AgentContext(task=task, agent_id="doc-intel-1", llm=llm or replay().for_plugin("doc_intel"), artifacts=store,
                       context=InMemoryContextStore(), logger=None, _progress=record)
    return await DocIntelAgent().handle(task, ctx), ctx, progress


def test_plugin_shape() -> None:
    validate_plugin(PLUGIN)
    assert PLUGIN.priority > 0 and [a.capabilities for a in PLUGIN.agents] == [(DOCUMENT_EXTRACT,)]
    assert not DocIntelAgent.is_stub and DocIntelAgent.max_slots == 1


async def test_agent_returns_requirement_set_and_document_model() -> None:
    result, ctx, progress = await _run_agent([("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf",
                                               None)])
    assert result.outcome == "success" and [r.artifact_type for r in result.artifact_refs] == [
        "requirement-set", "document-model"]
    rs = await ctx.get_json(result.artifact_refs[0], RequirementSet)
    model = await ctx.get_json(result.artifact_refs[1], DocumentModel)
    assert rs.project_id == PROJECT and len(rs.requirements) == 8 and rs.total_marks == 100
    assert rs.source_docs == ctx.task.artifact_refs
    assert all(r.source_ref.doc_id == ctx.task.artifact_refs[0].artifact_id and r.source_ref.quote
               for r in rs.requirements)
    assert model.documents[0].name == "tcp_chat_assignment.pdf"
    assert "8 requirements" in (result.summary or "") and "ocr_pages=0" in result.evidence
    assert progress[-1] == (100, "Requirements ready") and any("page 1 of 1" in s for _, s in progress)


async def test_agent_keeps_folders_and_names_typed_requests() -> None:
    result, ctx, _ = await _run_agent([("brief.md", b"# Part A\n\n- The API must return JSON.\n", "text/markdown",
                                        "Part A")])
    rs = await ctx.get_json(result.artifact_refs[0], RequirementSet)
    assert rs.requirements[0].source_ref.folder == "Part A"
    assert document_name("a", "text/plain", {}, only_one=True, index=1) == "request.txt"
    assert document_name("a", "application/pdf", {}, only_one=False, index=2) == "document-2.pdf"
    assert document_name("a", "application/pdf", {"name": "x.pdf"}, only_one=False, index=2) == "x.pdf"


async def test_redelivered_task_does_no_model_work_twice() -> None:
    """Item 2.8 "idempotent on redelivery": the runtime's inbox drops exact duplicates; if the same task still runs
    again (e.g. after a crash before the ack), the agent answers from its cache: same set, no new model calls."""
    sentence = f"The kiosk must print a receipt for order {new_task_id()}."  # unique: nothing cached yet
    fake = FakeLLM().on_schema(ChunkExtraction, ChunkExtraction(items=[
        ExtractedItem(kind="requirement", text=sentence, quote=sentence)]))
    first, ctx, _ = await _run_agent([("brief.md", f"# Kiosk\n\n- {sentence}\n".encode(), "text/markdown", None)],
                                     llm=fake)
    calls = len(fake.calls)
    again, ctx2, _ = await _run_agent([], llm=fake, task=ctx.task, store=ctx.artifacts)
    assert len(fake.calls) == calls == 1
    rs1 = await ctx.get_json(first.artifact_refs[0], RequirementSet)
    rs2 = await ctx2.get_json(again.artifact_refs[0], RequirementSet)
    assert rs1 == rs2 and rs1.requirements[0].text == sentence
    model1 = await ctx.get_json(first.artifact_refs[1], DocumentModel)
    model2 = await ctx2.get_json(again.artifact_refs[1], DocumentModel)
    assert model1.extraction.answered_by == {"fake:fake": 1} and model2.extraction.answered_by == {"memory": 1}


async def test_replayed_answers_name_the_recorded_model() -> None:
    DocIntelAgent.cache = LruCache()  # no answers from earlier tests: every part must come from the recording
    _, ctx, _ = await _run_agent([("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf", None)])
    refs = [r for r in await ctx.artifacts.list(PROJECT) if r.artifact_type == "document-model"]
    model = await ctx.get_json(refs[-1], DocumentModel)
    [(who, parts)] = model.extraction.answered_by.items()
    assert who.startswith("cache:") and parts == 1  # replayed, and the recorded model's name is kept
    assert model.extraction.prompt_version == "3" and model.extraction.quotes["exact"] >= 8


async def test_agent_without_documents_is_an_invalid_task() -> None:
    with pytest.raises(HmapError, match="at least one uploaded document"):
        await _run_agent([])


async def test_lru_cache_is_bounded() -> None:
    cache = LruCache(max_entries=2)
    for k in "abc":
        await cache.put(k, k)
    assert await cache.get("a") is None and await cache.get("c") == "c"


async def test_requirements_ready_event() -> None:
    emitted: list[DomainEvent] = []
    rs_ref = {"artifact_id": "A-1", "artifact_type": "requirement-set", "version": 1, "uri": "mem://x",
              "sha256": "0" * 64, "media_type": "application/json", "size_bytes": 2, "created_by": "a",
              "created_at": "2026-10-12T00:00:00Z", "access_scope": PROJECT}

    class Handle:
        async def get_task(self, task_id: str) -> dict[str, Any]:
            return {"project_id": PROJECT, "executions": [{"status": "SUCCEEDED", "result_refs": [rs_ref]}]}

        async def emit(self, event: DomainEvent) -> None:
            emitted.append(event)

    await announce_requirements.fn(DomainEvent(event_type="task.completed", aggregate_id="T-1"), Handle())  # type: ignore[arg-type]
    assert emitted[0].event_type == "project.requirements_ready" and emitted[0].project_id == PROJECT
    assert emitted[0].data["requirement_set_ref"]["artifact_id"] == "A-1"


# ---------------------------------------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=replay(),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def _poll(client: TestClient, url: str, pred: Any, timeout: float = 15.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(url)
        if r.status_code == 200 and pred(r.json()):
            return r.json()
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}")


def test_upload_to_requirements_edit_and_ownership(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "TCP chat"}).json()["project_id"]
    assert client.get(f"/api/doc_intel/requirements/{pid}").status_code == 404
    up = client.post(f"/api/projects/{pid}/documents",
                     files={"file": ("tcp_chat_assignment.pdf", PDF.read_bytes(), "application/pdf")})
    assert up.status_code == 201
    doc_id = up.json()["artifact"]["artifact_id"]
    # extract -> plan with no manual step
    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")

    got = client.get(f"/api/doc_intel/requirements/{pid}").json()
    rs = got["requirement_set"]
    assert len(rs["requirements"]) == 8 and rs["total_marks"] == 100 and got["artifact"]["version"] == 1
    events = [e["event_type"] for e in client.get("/api/events", params={"project_id": pid}).json()]
    assert "project.requirements_ready" in events

    rs["requirements"][0]["text"] = "The server must accept at least 20 clients."
    edit = {"artifact_id": got["artifact"]["artifact_id"], "base_version": 1, "requirement_set": rs}
    saved = client.put(f"/api/doc_intel/requirements/{pid}", json=edit)
    assert saved.status_code == 200 and saved.json()["artifact"]["version"] == 2
    assert saved.json()["artifact"]["created_by"].startswith("user:") and len(saved.json()["versions"]) == 2
    assert client.get(f"/api/doc_intel/requirements/{pid}").json()["requirement_set"]["requirements"][0][
        "text"].endswith("20 clients.")
    assert client.get(f"/api/doc_intel/requirements/{pid}", params={"version": 1}).json()["artifact"]["version"] == 1
    assert client.put(f"/api/doc_intel/requirements/{pid}", json=edit).status_code == 409  # stale base version
    bad = {**edit, "base_version": 2, "requirement_set": {**rs, "total_marks": 99}}
    r = client.put(f"/api/doc_intel/requirements/{pid}", json=bad)
    assert r.status_code == 422 and "Not saved" in r.json()["detail"]

    model = client.get(f"/api/doc_intel/document-model/{pid}").json()
    assert model["documents"][0]["doc_id"] == doc_id
    page = client.get(f"/api/doc_intel/pages/{pid}/{doc_id}/1")
    assert page.status_code == 200 and page.headers["content-type"] == "image/png" and page.content[:4] == b"\x89PNG"
    assert client.get(f"/api/doc_intel/pages/{pid}/{doc_id}/9").status_code == 404

    other = second_client(client)
    signed_in(other)
    for url in (f"/api/doc_intel/requirements/{pid}", f"/api/doc_intel/document-model/{pid}",
                f"/api/doc_intel/pages/{pid}/{doc_id}/1"):
        assert other.get(url).status_code == 404
    assert other.put(f"/api/doc_intel/requirements/{pid}", json=edit).status_code == 404

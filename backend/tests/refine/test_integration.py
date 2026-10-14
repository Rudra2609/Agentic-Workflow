"""Refinement on the running platform (items 4.8, 4.9, 4.10, 4.12-4.14): the project setting reaches the agent
runtime, Member 2's and Member 3's results are refined through the hook (their code untouched), the trace and
``refine.*`` events appear, the API shows runs / outputs / diffs to the owner only, ``refine.run`` works standalone
and is idempotent, and new agents opt in with the decorator or the mixin.

The model is scripted: Members 2 and 3 fall back to their rules (no answer for their schemas), the judge and the
reviser answer from the script below.
"""

import time
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from hmap.agents.refine import RefinementMixin, RefineSetup, refinable
from hmap.agents.refine.adapters import extraction as ex
from hmap.agents.refine.agent import RefineAgent
from hmap.agents.refine.critics import GENERIC_RUBRIC, LLMRubricCritic, ProgrammaticCritic
from hmap.agents.refine.critics.rubric import RubricAnswer
from hmap.agents.refine.revisers import TargetedReviser
from hmap.agents.refine.revisers.targeted import PatchAnswer
from hmap.api.app import create_app
from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.contracts.capabilities import REFINE_RUN
from hmap.core.contracts.domain import Issue, RequirementSet
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.llm import FakeLLM
from hmap.core.llm.fake import FakeCall
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

GOAL = ("Build a to-do list web app where I can add tasks and delete them.\n"
        "Tasks should be saved so they are still there after a refresh.\n"
        "Dark mode would be nice to have.")
MISSING = "Dark mode would be nice to have."


def scripted() -> FakeLLM:
    """The judge finds the missing sentence once, then nothing; the plan judge is satisfied; the reviser adds it."""
    seen: dict[str, int] = {}

    def judge(call: FakeCall) -> dict[str, Any]:
        subject = "plan" if "project plan" in call.messages[0].content else "extraction"
        seen[subject] = seen.get(subject, 0) + 1
        if subject == "extraction" and MISSING not in call.messages[1].content.split("=== Extracted items")[1]:
            return {"criteria": [{"id": "E1", "score": 2, "evidence": MISSING}], "issues": [
                {"criterion": "E1", "category": "OMISSION", "severity": "major", "location": "requirements",
                 "description": "A wish in the request is not listed.", "evidence": MISSING}]}
        return {"criteria": [{"id": "E1", "score": 5}, {"id": "P1", "score": 5}], "issues": []}

    fake = FakeLLM(default=None)
    fake.on_schema(RubricAnswer, judge)
    fake.on_schema(ex.ChangeAnswer, {"changes": [{"op": "add", "kind": "requirement", "priority": "could",
                                                  "text": "The app could offer a dark mode.", "quote": MISSING}]})
    return fake


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=scripted(),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def poll(client: TestClient, url: str, pred: Any, timeout: float = 30.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}: {body}")


def events(client: TestClient, pid: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = client.get("/api/events", params={"project_id": pid, "limit": 2000}).json()
    return out


def test_refine_is_off_by_default_and_changes_nothing(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "plain", "goal": GOAL}).json()
    assert project["refine"] is False
    pid = project["project_id"]
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    assert client.get(f"/api/refine/runs/{pid}").json() == []
    assert not [e for e in events(client, pid) if e["event_type"].startswith("refine.")]
    types = {a["artifact_type"] for a in client.get(f"/api/projects/{pid}/artifacts").json()}
    assert "refinement-trace" not in types


def test_refine_on_improves_the_requirements_and_checks_the_plan(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "refined", "goal": GOAL, "refine": True}).json()["project_id"]
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    runs = poll(client, f"/api/refine/runs/{pid}", lambda rs: len(rs) == 2 and all(r["status"] == "stopped"
                                                                                  for r in rs))
    by_cap = {r["capability"]: r for r in runs}
    extraction, plan = by_cap["document.extract"], by_cap["plan.generate"]
    assert extraction["applied"] and extraction["iterations"] == 1 and extraction["best_score"] > extraction[
        "base_score"]
    assert extraction["stop_reason"] in ("threshold", "no_critical_issues")
    assert not plan["applied"] and plan["iterations"] == 0 and plan["stop_reason"] == "threshold"

    # the improved set is the next version of Member 2's artifact, and the planner used it
    rs = client.get(f"/api/doc_intel/requirements/{pid}").json()
    assert rs["artifact"]["version"] == 2 and rs["artifact"]["created_by"].startswith("doc-intel")  # in its worker
    assert any(r["source_ref"]["quote"] == MISSING for r in rs["requirement_set"]["requirements"])
    plan_graph = client.get(f"/api/planning/plan/{pid}").json()
    added = next(r for r in rs["requirement_set"]["requirements"] if r["source_ref"]["quote"] == MISSING)
    assert added["id"] in plan_graph["graph"]["coverage_matrix"]

    # trace, outputs and diff
    run = client.get(f"/api/refine/runs/{pid}/{extraction['run_id']}").json()
    assert run["status"] == "stopped" and [it["index"] for it in run["iterations"]] == [0, 1]
    assert run["iterations"][0]["issues_by_category"].get("OMISSION", 0) >= 1
    assert run["iterations"][1]["strategy"] == "targeted" and run["iterations"][1]["revision_notes"]
    assert {c["critic"] for c in run["iterations"][0]["critics"]} >= {"quotes", "contract", "judge"}
    from hmap.core.contracts.domain import RefinementTrace

    RefinementTrace.model_validate(run)                                  # the stored record is the shared contract
    out0 = client.get(f"/api/refine/runs/{pid}/{extraction['run_id']}/outputs/0").json()
    assert len(out0["requirements"]) == len(rs["requirement_set"]["requirements"]) - 1
    diff = client.get(f"/api/refine/runs/{pid}/{extraction['run_id']}/diff", params={"a": 0, "b": 1}).json()
    assert [c["op"] for c in diff["changes"]] == ["added"] and diff["changes"][0]["path"].startswith("requirements/")
    assert client.get(f"/api/refine/runs/{pid}/{extraction['run_id']}/outputs/7").status_code == 404

    # refine.iteration / refine.stopped events (plan D5)
    ev = poll(client, f"/api/events?project_id={pid}&limit=2000",
              lambda es: len([e for e in es if e["event_type"] == "refine.stopped"]) == 2)
    ev = [e for e in ev if e["event_type"].startswith("refine.")]
    stopped = [e for e in ev if e["event_type"] == "refine.stopped"]
    assert {e["data"]["capability"] for e in stopped} == {"document.extract", "plan.generate"}
    assert any(e["event_type"] == "refine.iteration" and e["data"]["capability"] == "document.extract" for e in ev)
    task = client.get(f"/api/tasks/{extraction['task_id']}").json()
    assert "refinement-trace" in {r["artifact_type"] for r in task["executions"][-1]["result_refs"]}

    # owner only
    other = second_client(client)
    signed_in(other)
    for url in (f"/api/refine/runs/{pid}", f"/api/refine/runs/{pid}/{extraction['run_id']}",
                f"/api/refine/runs/{pid}/{extraction['run_id']}/diff"):
        assert other.get(url).status_code == 404


def test_project_toggle_and_standalone_refine_run(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "toggle", "goal": GOAL}).json()["project_id"]
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    assert client.patch(f"/api/projects/{pid}", json={"refine": True}).json()["refine"] is True
    rs = client.get(f"/api/doc_intel/requirements/{pid}").json()
    no_csrf = second_client(client)
    no_csrf.cookies = client.cookies
    no_csrf.headers.pop("X-CSRF-Token", None)
    assert no_csrf.post(f"/api/refine/runs/{pid}", json={"artifact_id": rs["artifact"]["artifact_id"]}
                        ).status_code == 403
    started = client.post(f"/api/refine/runs/{pid}", json={"artifact_id": rs["artifact"]["artifact_id"]})
    assert started.status_code == 202
    task_id = started.json()["task_id"]
    task = poll(client, f"/api/tasks/{task_id}", lambda t: t["state"] in ("COMPLETED", "FAILED"))
    assert task["state"] == "COMPLETED" and task["capability"] == REFINE_RUN
    refs = task["executions"][-1]["result_refs"]
    assert [r["artifact_type"] for r in refs] == ["requirement-set", "refinement-trace"] and refs[0]["version"] == 2
    assert client.post(f"/api/refine/runs/{pid}", json={"artifact_id": "nope"}).status_code == 404
    assert client.get("/api/refine/policy").json()["default"]["max_iters"] == 3


# ---------------------------------------------------------------------------------------------- new agents


class Notes(BaseAgent):
    """A new agent (e.g. Member 5's) that opts in with the decorator."""

    name = "notes"
    capabilities: ClassVar[tuple[str, ...]] = ("notes.write",)

    @refinable(lambda agent, task, ctx: RefineSetup(
        artifact_type="notes", load=lambda b: __import__("json").loads(b),
        critics=[ProgrammaticCritic(lambda out, i: [] if out.get("summary") else [Issue(
            category="OMISSION", severity="major", location="/summary", description="the summary is missing")])],
        reviser=TargetedReviser()))
    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        ref = await ctx.put_json({"title": "Notes", "summary": ""}, artifact_type="notes")
        return ctx.result([ref], summary="notes written")


class MixedNotes(RefinementMixin, Notes):
    name = "mixed-notes"

    def refine_setup(self, task: TaskAssign, ctx: AgentContext) -> RefineSetup:
        return RefineSetup(artifact_type="notes", load=lambda b: __import__("json").loads(b),
                           critics=[LLMRubricCritic(GENERIC_RUBRIC)], reviser=TargetedReviser(), reflexion=False)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        ref = await ctx.put_json({"title": "Notes", "summary": ""}, artifact_type="notes")
        return await self.refine(task, ctx.result([ref]), ctx)


def _ctx(task: TaskAssign, llm: Any, store: Any = None) -> AgentContext:
    return AgentContext(task=task, agent_id="test-agent", llm=llm, artifacts=store or InMemoryArtifactStore(),
                        context=InMemoryContextStore(), logger=None)


def _task(capability: str, refine: bool, **kw: Any) -> TaskAssign:
    return TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=capability,
                      objective="write notes", acceptance_criteria=[], context_refs=[], project_id="P-NEW",
                      refine=refine, **kw)


async def test_decorator_refines_only_with_the_flag() -> None:
    fake = FakeLLM(default=None).on_schema(PatchAnswer, {"patches": [
        {"op": "replace", "path": "/summary", "value_json": '"Three decisions were made."'}]})
    off = await Notes().handle(_task("notes.write", False), _ctx(_task("notes.write", False), fake))
    assert [r.artifact_type for r in off.artifact_refs] == ["notes"]
    task = _task("notes.write", True)
    ctx = _ctx(task, fake)
    on = await Notes().handle(task, ctx)
    assert [r.artifact_type for r in on.artifact_refs] == ["notes", "refinement-trace"]
    assert on.artifact_refs[0].version == 2 and "checked and improved" in (on.summary or "")
    import json

    assert json.loads(await ctx.artifacts.get(on.artifact_refs[0], project_id="P-NEW"))["summary"]


async def test_mixin_with_an_llm_judge_keeps_the_original_when_nothing_improves() -> None:
    fake = FakeLLM(default=None).on_schema(RubricAnswer, {"criteria": [{"id": "G1", "score": 5}], "issues": []})
    task = _task("notes.write", True)
    result = await MixedNotes().handle(task, _ctx(task, fake))
    assert [r.version for r in result.artifact_refs] == [1, 1] and "kept as is" in (result.summary or "")


async def test_refine_agent_generic_contract_and_idempotency() -> None:
    store = InMemoryArtifactStore()
    ref = await store.put(b'{"title": "x", "summary": ""}', project_id="P-NEW", artifact_type="notes",
                          media_type="application/json", created_by="user")
    fake = FakeLLM(default=None)
    fake.on_schema(RubricAnswer, {"criteria": [{"id": "G1", "score": 2}], "issues": [
        {"criterion": "G1", "category": "OMISSION", "severity": "major", "location": "/summary",
         "description": "the summary is empty"}]}, {"criteria": [{"id": "G1", "score": 5}], "issues": []})
    fake.on_schema(PatchAnswer, {"patches": [{"op": "replace", "path": "/summary", "value_json": '"Done."'}]})
    task = _task(REFINE_RUN, False, artifact_refs=[ref], inputs={"rubric": [{"id": "G1", "question": "complete?"}]})
    agent = RefineAgent()
    first = await agent.handle(task, _ctx(task, fake, store))
    assert [r.artifact_type for r in first.artifact_refs] == ["notes", "refinement-trace"]
    assert first.artifact_refs[0].version == 2
    calls = len(fake.calls)
    again = await agent.handle(task, _ctx(task, fake, store))          # redelivery: same input, no second loop
    assert len(fake.calls) == calls and [r.artifact_id for r in again.artifact_refs] == [
        r.artifact_id for r in first.artifact_refs]
    from hmap.core.errors import HmapError

    with pytest.raises(HmapError):
        bad = _task(REFINE_RUN, False, artifact_refs=[], inputs={})
        await agent.handle(bad, _ctx(bad, fake, store))


async def test_refine_agent_requirement_set_needs_its_document_model() -> None:
    store = InMemoryArtifactStore()
    rs = RequirementSet(project_id="P-NEW", requirements=[])
    ref = await store.put(rs.model_dump_json().encode(), project_id="P-NEW", artifact_type="requirement-set",
                          media_type="application/json", created_by="user")
    task = _task(REFINE_RUN, False, artifact_refs=[ref])
    from hmap.core.errors import HmapError

    with pytest.raises(HmapError, match="document-model"):
        await RefineAgent().handle(task, _ctx(task, FakeLLM(), store))

#!/usr/bin/env python3
"""Sprint 10 demo (Member 10: final review & recovery), offline, no model.

1. The 12 seeded failures of the golden scenario through the real review modules: category, the responsible step,
   the minimal recovery plan, the stop rule (and the naive "first covering task" baseline getting it wrong).
2. The closed loop on the real Manager + API + review agent (the platform's in-memory stack), with scripted coding /
   testing / docs agents so the failure is the same every time:
   a. guide §32: the multi-client test fails in server.py -> REVISE -> only the server step is revised, test and
      docs re-run (the client step is not) -> review round 1 PASS -> project COMPLETED;
   b. a fix that never helps -> plateau -> ESCALATE, the project waits for a person (REVIEWING) -> accept with
      notes in the Review API -> COMPLETED.

Run from backend/: ``uv run python ../scripts/demo_sprint_10.py`` (``demo_sprint_10.sh`` does, then replays the
recorded golden TCP-chat scenario on the whole platform). Exits non-zero if a check fails.
"""

import io
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from hmap.agents.review.plugin import PLUGIN as REVIEW  # noqa: E402
from hmap.api.app import create_app  # noqa: E402
from hmap.core.contracts import CodeChangeSet, DocBundle, RequirementSet, TaskAssign, TaskGraph, TaskResult, TestReport  # noqa: E402
from hmap.core.contracts.domain import AccuracyReport, PlanTask, StageResult, TestFailure  # noqa: E402
from hmap.core.llm import FakeLLM  # noqa: E402
from hmap.core.plugins import Plugin  # noqa: E402
from hmap.core.runtime.base import AgentContext, BaseAgent  # noqa: E402
from hmap.system import HmapSystem, SystemConfig  # noqa: E402
from tests.api.helpers import signed_in  # noqa: E402
from tests.review.helpers import run_scenario, scenarios  # noqa: E402

WORLD: dict[str, Any] = {}


def check(ok: bool, what: str) -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")
    if not ok:
        raise SystemExit(1)


class Coder(BaseAgent):
    name = "scripted-coder"
    capabilities: ClassVar[tuple[str, ...]] = ("code.implement", "code.revise")

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        text = " ".join([task.objective, *task.acceptance_criteria]).lower()
        f = "server.py" if "server" in text else "client.py"
        if task.capability == "code.revise" and WORLD["fixable"]:
            await ctx.put_json({"fixed": True}, artifact_type="scripted-fix", artifact_id=f"fix-{f}")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"import threading\n"
            info = tarfile.TarInfo(f)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        ws = await ctx.artifacts.put(buf.getvalue(), project_id=ctx.project_id, artifact_type="workspace",
                                     media_type="application/gzip", created_by=ctx.agent_id,
                                     artifact_id=f"ws-{task.task_id}")
        cs = CodeChangeSet(task_id=task.task_id, workspace_ref=ws, files_changed=[f],
                           notes="Fully concurrent and production ready.")
        return ctx.result([await ctx.put_json(cs, artifact_type="code-change-set", artifact_id=f"cs-{task.task_id}")])


class Tester(BaseAgent):
    name = "scripted-tester"
    capabilities: ClassVar[tuple[str, ...]] = ("test.run",)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        fixed = await ctx.artifacts.latest("fix-server.py", project_id=ctx.project_id) is not None
        fails = [] if fixed else [TestFailure(category="ASSERTION", file="server.py",
                                              message="test_two_clients_chat: client 2 never gets the broadcast "
                                                      "(the server serves one client at a time)")]
        rep = TestReport(task_id=task.task_id, stages={"integration": StageResult(status="passed" if fixed else
                                                                                  "failed")},
                         failures=fails, passed=fixed)
        tt = await ctx.put_json({"loop": {"round": (task.inputs.get("loop") or {}).get("round", 0)},
                                 "failures": [f.model_dump() for f in fails]},
                                artifact_type="testing-trace", artifact_id=f"tt-{task.task_id}")
        return ctx.result([await ctx.put_json(rep, artifact_type="test-report", artifact_id=f"tr-{task.task_id}"),
                           tt])


class Docs(BaseAgent):
    name = "scripted-docs"
    capabilities: ClassVar[tuple[str, ...]] = ("docs.generate", "docs.update")

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        readme = await ctx.put_json({"md": "# Chat"}, artifact_type="doc-readme", artifact_id=f"drd-{task.task_id}")
        b = DocBundle(task_id=task.task_id, readme_ref=readme, accuracy_report=AccuracyReport(grounded_pct=100))
        return ctx.result([await ctx.put_json(b, artifact_type="doc-bundle", artifact_id=f"db-{task.task_id}")])


def seeded() -> None:
    print("\n1. Seeded failures through the real review modules")
    base, scen = scenarios()
    ok = naive_ok = 0
    for s in scen:
        got = run_scenario(s, base)
        naive = run_scenario(s, base, naive=True)
        want = s["expect"]
        good = all(got.get(k) == v for k, v in want.items())
        ok += good
        naive_ok += naive["failures"] == want["failures"]
        fails = ", ".join(f"{r} {c} -> {t or 'no step'}" for r, c, t in got["failures"])
        acts = ", ".join(f"{a} {t}" for a, t in got["actions"])
        end = got["outcome"] + (f" ({got['reason']})" if got.get("reason") else "")
        print(f"   {'ok  ' if good else 'FAIL'} {s['id']:27s} {fails:46s} | {acts:28s} | {end}")
    check(ok == len(scen), f"{ok}/{len(scen)} scenarios recover or escalate as expected")
    check(naive_ok < len(scen), f"the naive 'first covering task' attribution gets only {naive_ok}/{len(scen)} right")


def project(client: TestClient, system: HmapSystem, name: str) -> str:
    pid: str = client.post("/api/projects", json={"name": name}).json()["project_id"]
    src = {"doc_id": "assignment"}
    rs = RequirementSet.model_validate({"project_id": pid, "requirements": [
        {"id": "R1", "text": "The server must accept connections from at least 10 concurrent clients.",
         "source_ref": src},
        {"id": "R2", "text": "Every message is broadcast to all other connected clients.", "source_ref": src},
        {"id": "R3", "text": "/quit disconnects the client cleanly.", "source_ref": src}],
        "deliverables": [{"id": "D1", "name": "A README explaining how to run the server and the client"}]})
    graph = TaskGraph(project_id=pid, tasks=[
        PlanTask(id="T1", title="Write the server", agent_capability="code.implement", requirement_ids=["R1", "R2"]),
        PlanTask(id="T2", title="Write the client", agent_capability="code.implement", requirement_ids=["R3"]),
        PlanTask(id="T3", title="Test the chat", agent_capability="test.run", depends_on=["T1", "T2"],
                 requirement_ids=["R1", "R2", "R3"], phase="test"),
        PlanTask(id="T4", title="Write the README", agent_capability="docs.generate", depends_on=["T3"],
                 phase="document"),
        PlanTask(id="T5", title="Final review", agent_capability="review.final", depends_on=["T4"], phase="review")],
        coverage_matrix={"R1": ["T1", "T3"], "R2": ["T1", "T3"], "R3": ["T2", "T3"], "D1": ["T4"]})

    async def go() -> None:
        for obj, typ in ((rs, "requirement-set"), (graph, "task-graph")):
            await system.artifacts.put(obj.model_dump_json().encode(), project_id=pid, artifact_type=typ,
                                       media_type="application/json", created_by="demo")
        await system.manager.submit_graph(pid, graph, require_approval=False)
    client.portal.call(go)  # type: ignore[union-attr]
    return pid


def wait(client: TestClient, pid: str, states: tuple[str, ...]) -> dict[str, Any]:
    for _ in range(600):
        p: dict[str, Any] = client.get(f"/api/projects/{pid}").json()
        if p["state"] in states:
            return p
        time.sleep(0.05)
    raise SystemExit(f"FAIL: project {pid} did not settle")


def show_rounds(client: TestClient, pid: str) -> list[dict[str, Any]]:
    rounds: list[dict[str, Any]] = client.get(f"/api/review/reports/{pid}").json()["rounds"]
    for r in rounds:
        detail = client.get(f"/api/review/reports/{pid}/{r['task_id']}").json()
        names = {t["task_id"]: t["title"] for t in detail["tasks"]}
        print(f"   round {r['round']}: {r['recommendation']} ({round((r['completeness'] or 0) * 100)} % complete)")
        for f in detail["report"]["failures"]:
            print(f"     - {f['requirement_id']} {f['category']} -> {names.get(f['responsible_task_id'], '?')}: "
                  f"{f['description'][:90]}")
        if r["created_tasks"]:
            print("     next: " + " -> ".join(f"{t['action']} {t['title'].split(': ', 1)[-1][:40]}"
                                              for t in r["created_tasks"]))
        if r["stop_reason"]:
            print(f"     stopped: {r['stop_reason']}")
    return rounds


def closed_loop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        system = HmapSystem.in_memory(artifact_root=Path(tmp) / "artifacts", llm=FakeLLM(default=None),
                                      plugins=[REVIEW, Plugin(name="scripted", agents=[Coder, Tester, Docs],
                                                              priority=200)],
                                      config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
        with TestClient(create_app(system, run_agents=True)) as client:
            signed_in(client, name="Sprint 10 demo", email="sprint10-demo@example.test")
            print("\n2a. The multi-client failure (guide §32) -> targeted revision -> PASS")
            WORLD.update(fixable=True)
            pid = project(client, system, "Sprint 10: TCP chat")
            p = wait(client, pid, ("COMPLETED", "FAILED", "REVIEWING"))
            rounds = show_rounds(client, pid)
            made = {t["capability"] for t in rounds[0]["created_tasks"]}
            check(rounds[0]["recommendation"] == "REVISE" and rounds[-1]["recommendation"] == "PASS",
                  "round 0 REVISE, the last round PASS")
            check(made == {"code.revise", "test.run", "docs.update", "review.final"},
                  "only the server step is revised; tests, docs and the review run again; the client step is not")
            check(p["state"] == "COMPLETED", "the project completes after the PASS review")
            outcomes: list[str] = []
            for _ in range(100):           # the hook emits right after the run settles
                events = client.get("/api/events", params={"project_id": pid}).json()
                outcomes = [e["data"]["outcome"] for e in events if e["event_type"] == "review.completed"]
                if outcomes[-1:] == ["PASS"]:
                    break
                time.sleep(0.05)
            check(outcomes == ["REVISE", "PASS"], "review.completed REVISE, then PASS")

            print("\n2b. A fix that never helps -> plateau -> a person decides")
            WORLD.update(fixable=False)
            pid = project(client, system, "Sprint 10: stuck fix")
            p = wait(client, pid, ("COMPLETED", "FAILED", "REVIEWING"))
            rounds = show_rounds(client, pid)
            check(p["state"] == "REVIEWING" and (rounds[-1]["stop_reason"] or "").startswith("plateau"),
                  "ESCALATE (plateau): the project waits for a person, with the reason")
            r = client.post(f"/api/review/reports/{pid}/{rounds[-1]['task_id']}/accept",
                            json={"notes": "known limitation: single-threaded server, explained in the report"})
            check(r.status_code == 200, "accept with notes (Review API)")
            p = wait(client, pid, ("COMPLETED",))
            check(p["state"] == "COMPLETED", "accepted -> the project completes")


def main() -> None:
    seeded()
    closed_loop()
    print("\nSprint 10 demo OK")


if __name__ == "__main__":
    main()

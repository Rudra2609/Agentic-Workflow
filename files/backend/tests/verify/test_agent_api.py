"""The verify agent on the bus (6.7), the follow-up loop (6.8) and the API (6.11), in memory with a fake model."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.agents.verify import benchmark
from hmap.api.app import create_app
from hmap.core.contracts import ArtifactRef, ResearchReport, VerificationReport
from hmap.core.contracts.capabilities import VERIFY_CLAIMS
from hmap.core.llm import FakeLLM
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

REPORT = benchmark.BENCH_DIR / "source_reports" / "q06_token_scheme.json"
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_RESEARCH_CACHE_DIR", str(tmp_path / "rcache"))
    monkeypatch.setenv("HMAP_VERIFY_CACHE_DIR", str(tmp_path / "vcache"))
    monkeypatch.setenv("HMAP_RESEARCH_MODE", "cached")
    monkeypatch.setenv("HMAP_VERIFY_MAX_ROUNDS", "1")
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=FakeLLM(default=None),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


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


def system_of(client: TestClient) -> HmapSystem:
    s: HmapSystem = client.app.state.system  # type: ignore[attr-defined]
    return s


def store_report(client: TestClient, pid: str, *, tamper: str | None = None) -> ArtifactRef:
    """Member 5's artifacts as the research step leaves them: one research-page per cited page + the report."""
    system = system_of(client)
    report = ResearchReport.model_validate_json(REPORT.read_text())
    pages = {p.content_sha256: p for f in benchmark.PAGES_DIR.glob("*.json")
             if (p := benchmark.page_file(f"pages/{f.name}")) is not None}

    async def put() -> ArtifactRef:
        refs: dict[str, ArtifactRef] = {}
        for e in report.evidence:
            if e.content_sha256 not in refs:
                body = pages[e.content_sha256].model_dump_json().encode()
                refs[e.content_sha256] = await system.artifacts.put(
                    body, project_id=pid, artifact_type="research-page", media_type="application/json",
                    created_by="research", artifact_id=f"rp-{e.content_sha256[:32]}")
        evidence = [e.model_copy(update={"page_artifact": refs[e.content_sha256],
                                         "quote": tamper if (tamper and e.id == "E1") else e.quote})
                    for e in report.evidence]
        body = report.model_copy(update={"evidence": evidence}).model_dump_json().encode()
        return await system.artifacts.put(body, project_id=pid, artifact_type="research-report",
                                          media_type="application/json", created_by="research")

    return client.portal.call(put)  # type: ignore[union-attr]


def create(client: TestClient, pid: str, refs: list[ArtifactRef], **inputs: Any) -> str:
    async def go() -> str:
        return await system_of(client).manager.create_task(pid, VERIFY_CLAIMS, "Check the research findings",
                                                           artifact_refs=refs, inputs=inputs or None)
    return client.portal.call(go)  # type: ignore[union-attr]


def report_of(client: TestClient, task: dict[str, Any]) -> VerificationReport:
    ref = next(r for r in task["executions"][-1]["result_refs"] if r["artifact_type"] == "verification-report")
    pid = task["project_id"]

    async def get() -> bytes:
        return await system_of(client).artifacts.get(ArtifactRef.model_validate(ref), project_id=pid)
    return VerificationReport.model_validate_json(client.portal.call(get))  # type: ignore[union-attr]


def test_verify_step_follow_up_loop_and_api(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "verify"}).json()["project_id"]
    ref = store_report(client, pid, tamper="This is a stateful authentication mechanism kept in server memory")
    tid = create(client, pid, [ref])
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in DONE)
    assert task["state"] == "COMPLETED"
    types = [r["artifact_type"] for r in task["executions"][-1]["result_refs"]]
    assert types == ["verification-report", "verification-trace"]
    report = report_of(client, task)
    by_id = {v.claim_id: v for v in report.claim_verdicts}
    assert len(by_id) == 7 and by_id["C1"].verdict == "UNSUPPORTED" and "E1" in by_id["C1"].contradicting
    assert "word for word" in by_id["C1"].explanation and report.research_report_ref == ref
    assert report.follow_up_questions

    # the hook: verification.completed + ONE follow-up round (research on the gaps, then a re-check), then stop
    def tasks() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = client.get(f"/api/projects/{pid}/tasks").json()
        return out

    def settled(ts: list[dict[str, Any]]) -> bool:
        checks = [t for t in ts if t["capability"] == VERIFY_CLAIMS]
        return len(checks) == 2 and all(t["state"] in DONE for t in ts)

    deadline = time.time() + 90
    while not settled(tasks()) and time.time() < deadline:
        time.sleep(0.1)
    ts = tasks()
    research = [t for t in ts if t["capability"] == "research.run"]
    checks = [t for t in ts if t["capability"] == VERIFY_CLAIMS]
    assert len(research) == 1 and research[0]["parent_task_id"] == tid
    assert research[0]["inputs"]["follow_up_of"]["artifact_id"] == ref.artifact_id
    assert research[0]["inputs"]["research_questions"] == report.follow_up_questions
    recheck = next(t for t in checks if t["task_id"] != tid)
    assert recheck["depends_on"] == [research[0]["task_id"]] and recheck["inputs"]["verify_round"] == 1
    time.sleep(0.5)
    assert len([t for t in tasks() if t["capability"] == VERIFY_CLAIMS]) == 2            # bounded: no 3rd round
    events = client.get("/api/events", params={"project_id": pid, "limit": 500}).json()
    done = [e for e in events if e["event_type"] == "verification.completed"]
    first = next(e for e in done if e["aggregate_id"] == tid)
    assert first["data"]["summary"]["unsupported"] >= 1 and first["data"]["round"] == 0
    assert first["data"]["follow_up"]["research_task_id"] == research[0]["task_id"]

    # API
    runs = client.get(f"/api/verify/runs/{pid}").json()
    assert {r["task_id"] for r in runs} == {tid, recheck["task_id"]}
    detail = client.get(f"/api/verify/runs/{pid}/{tid}").json()
    c1 = next(c for c in detail["trace"]["claims"] if c["claim_id"] == "C1")
    assert c1["evidence"][0]["page_artifact"]["artifact_id"].startswith("rp-") and c1["atoms"][0]["l1"]
    assert detail["follow_ups"] and detail["follow_ups"][0]["capability"] == "research.run"
    assert len(client.get("/api/verify/table").json()) == 8
    asked = client.post(f"/api/verify/runs/{pid}/{tid}/follow-up", json={"claim_ids": ["C1"]})
    assert asked.status_code == 202 and set(asked.json()) == {"research_task_id", "verify_task_id"}
    other = second_client(client)
    signed_in(other)
    assert other.get(f"/api/verify/runs/{pid}").status_code == 404
    assert other.get(f"/api/verify/runs/{pid}/{tid}").status_code == 404
    assert client.get(f"/api/verify/runs/{pid}/nope").status_code == 404


def test_no_report_is_nothing_to_verify_and_redelivery_is_idempotent(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "empty"}).json()["project_id"]
    tid = create(client, pid, [])
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in DONE)
    assert task["state"] == "COMPLETED" and report_of(client, task).claim_verdicts == []
    assert "nothing to verify" in json.dumps(client.get(f"/api/verify/runs/{pid}/{tid}").json()["trace"]["notes"])

    ref = store_report(client, pid)
    t2 = create(client, pid, [ref], stub_fail="TOOL_TRANSIENT", stub_fail_times=1)   # first attempt fails
    task2 = poll(client, f"/api/tasks/{t2}", lambda t: t["state"] in DONE)
    assert task2["state"] == "COMPLETED" and len(task2["executions"]) == 2

    from hmap.agents.verify.agent import VerifyAgent

    agent = VerifyAgent()
    system = system_of(client)

    async def again() -> list[str]:
        from hmap.core.contracts import TaskAssign
        from hmap.core.runtime.base import AgentContext

        assign = TaskAssign(task_id=t2, execution_id="E-again", capability=VERIFY_CLAIMS, objective="x",
                            project_id=pid, artifact_refs=[ref], acceptance_criteria=[], context_refs=[])
        ctx = AgentContext(task=assign, agent_id="verify-test", llm=FakeLLM(default=None),
                           artifacts=system.artifacts, context=system.contexts, logger=None)
        res = await agent.handle(assign, ctx)
        return [f"{r.artifact_id}@{r.version}" for r in res.artifact_refs]

    first = [f"{r['artifact_id']}@{r['version']}" for r in task2["executions"][-1]["result_refs"]]
    assert client.portal.call(again) == first                                            # type: ignore[union-attr]

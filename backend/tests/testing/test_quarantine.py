"""Stretch: flaky-test quarantine (in, does not count, clean passes, released; stored per project; API)."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hmap.agents.testing import quarantine
from hmap.agents.testing.agent import TestingAgent
from hmap.agents.testing.model import FailureRecord
from hmap.agents.testing.sandbox import RunResult, Step, StepResult
from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.contracts import TaskAssign, TestReport
from hmap.core.contracts.capabilities import TEST_RUN
from hmap.core.llm import FakeLLM
from hmap.core.runtime.base import AgentContext
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

NODE = "test_m.py::test_x"


def fail(node: str = NODE) -> FailureRecord:
    return FailureRecord(stage="unit", category="ASSERTION", test=node, message=f"{node}: assert 1 == 2")


def test_apply_update_release() -> None:
    q = quarantine.Quarantine(project_id="P")
    assert quarantine.update(q, flaky=[NODE], failed=set(), passed=set(), task_id="T1")
    f = fail()
    assert quarantine.apply(q, [f, fail("test_m.py::test_other")]) == [NODE]
    assert f.flaky and "quarantined" in (f.hint or "")
    for i in range(quarantine.RELEASE_AFTER - 1):
        quarantine.update(q, flaky=[], failed=set(), passed={NODE}, task_id=f"T{i}")
        assert NODE in q.tests
    quarantine.update(q, flaky=[], failed=set(), passed={NODE}, task_id="T9")
    assert NODE not in q.tests and q.released == [NODE]
    quarantine.update(q, flaky=[NODE], failed=set(), passed=set(), task_id="T10")
    quarantine.update(q, flaky=[], failed=set(), passed={NODE}, task_id="T11")
    quarantine.update(q, flaky=[], failed={NODE}, passed=set(), task_id="T12")    # a failure resets nothing new
    assert q.tests[NODE].clean_passes == 1
    assert quarantine.release(q, NODE) and not quarantine.release(q, NODE)


class FlakyOnceBackend:
    """test_x fails in every pipeline run, passes on the re-check; test_y always passes."""
    name, isolation = "fake", "none"

    async def run(self, files: dict[str, str], steps: list[Step], *, cancelled: object = None,
                  image: str | None = None) -> RunResult:
        if [s.name for s in steps] == ["recheck"]:
            xml = '<testsuites><testsuite><testcase classname="test_m" name="test_x"/></testsuite></testsuites>'
            return RunResult(backend="fake", steps=[StepResult(name="recheck", stage="unit", exit_code=0,
                                                               files={".xml": xml})])
        xml = ('<testsuites><testsuite><testcase classname="test_m" name="test_x"><failure message="AssertionError: '
               'assert 1 == 2">E   AssertionError: assert 1 == 2</failure></testcase>'
               '<testcase classname="test_m" name="test_y"/></testsuite></testsuites>')
        return RunResult(backend="fake", steps=[
            StepResult(name=s.name, stage=s.stage, exit_code=1 if s.name == "unit" else 0,
                       files={".xml": xml} if s.name == "unit" else {}) for s in steps])


async def test_the_agent_quarantines_and_stops_counting(tmp_path: Path) -> None:
    from hmap.agents.coding.workspace import Workspace, pack
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "m.py").write_text("def f():\n    return 1\n")
    (tmp_path / "ws" / "test_m.py").write_text("from m import f\n\ndef test_x():\n    assert f() == 1\n")
    store = InMemoryArtifactStore()
    ws = await store.put(pack(Workspace(tmp_path / "ws")), project_id="P", artifact_type="workspace",
                         media_type="application/gzip", created_by="t")
    agent = TestingAgent(Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "w")}), backend=FlakyOnceBackend())
    for n in (1, 2):
        task = TaskAssign(task_id=f"T{n}", execution_id=f"E{n}", capability=TEST_RUN, objective="o",
                          acceptance_criteria=[], context_refs=[], project_id="P", artifact_refs=[ws])
        ctx = AgentContext(task=task, agent_id="a", llm=FakeLLM(default=None), artifacts=store,
                           context=InMemoryContextStore(), logger=logging.getLogger("t"))
        res = await agent.handle(task, ctx)
        report = TestReport.model_validate_json(await store.get(res.artifact_refs[0], project_id="P"))
        assert report.passed                      # run 1: flaky (re-check passed); run 2: quarantined
        assert report.failures[0].message.startswith("[flaky]")
    q = await quarantine.load(store, "P")
    assert list(q.tests) == ["test_m.py::test_x"] and q.tests["test_m.py::test_x"].flaky == 2


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=FakeLLM(default=None),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=False)) as c:
        signed_in(c)
        yield c


def system_of(client: TestClient) -> HmapSystem:
    s: HmapSystem = client.app.state.system  # type: ignore[attr-defined]
    return s


def test_quarantine_api(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "q"}).json()["project_id"]
    q = quarantine.Quarantine(project_id=pid)
    quarantine.update(q, flaky=[NODE], failed=set(), passed=set(), task_id="T1")

    async def put() -> None:
        await quarantine.save(system_of(client).artifacts, q, "t")
    client.portal.call(put)  # type: ignore[union-attr]
    body = client.get(f"/api/testing/quarantine/{pid}").json()
    assert list(body["tests"]) == [NODE] and body["release_after"] == quarantine.RELEASE_AFTER
    other = second_client(client)
    signed_in(other)
    assert other.get(f"/api/testing/quarantine/{pid}").status_code == 404
    assert client.post(f"/api/testing/quarantine/{pid}/release", json={"test": "nope"}).status_code == 404
    r = client.post(f"/api/testing/quarantine/{pid}/release", json={"test": NODE})
    assert r.status_code == 200 and r.json()["tests"] == {} and r.json()["released"] == [NODE]

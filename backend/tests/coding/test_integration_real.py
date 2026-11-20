"""Over the real stack (item 7.15): API -> Manager on PostgreSQL -> RabbitMQ -> CodingAgent -> changeset + workspace +
patch + trace -> ``code.completed`` -> "Request changes" -> ``code.revise`` from the project head. Scripted FakeLLM:
no network, keys or Ollama. Skipped (with the reason) when ``make infra-up`` has not run."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.runtime.discovery import discover
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.system import HmapSystem
from tests.api.helpers import signed_in
from tests.coding.test_agent_api import DONE, TYPES, create, fake_llm, get_bytes, hidden_pass, poll, put_starter
from tests.core.bus.conftest import delete_namespace, make_rabbit_bus, new_namespace
from tests.e2e.test_full_stack import CFG, infra, persistence  # noqa: F401  (module fixture re-used)

pytestmark = pytest.mark.integration


@pytest.fixture
def stack(infra: tuple[str, str], tmp_path: Any,  # noqa: F811
          monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    url, schema = infra
    monkeypatch.setenv("HMAP_CODING_WORK_DIR", str(tmp_path / "work"))
    ns = new_namespace()
    system = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"),
                        llm=fake_llm(), plugins=discover(), config=CFG, persistence=persistence(url, schema))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c
    asyncio.run(delete_namespace(ns))


def test_code_implement_and_revise_on_rabbitmq_and_postgres(stack: TestClient) -> None:
    from hmap.agents.coding.workspace import files_from_tar

    client = stack
    pid = client.post("/api/projects", json={"name": "coding-real"}).json()["project_id"]
    start = put_starter(client, pid)
    tid = create(client, pid, workspace_ref=start.model_dump(mode="json"))
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in DONE, timeout=120)
    assert task["state"] == "COMPLETED"
    refs = task["executions"][-1]["result_refs"]
    assert [r["artifact_type"] for r in refs] == TYPES
    assert hidden_pass(files_from_tar(get_bytes(client, pid, refs[1])))
    events = client.get("/api/events", params={"project_id": pid, "limit": 500}).json()
    assert [e["data"]["files_changed"] for e in events if e["event_type"] == "code.completed"] == [["stats.py"]]
    r = client.post(f"/api/coding/runs/{pid}/{tid}/revise", json={"required_changes": ["document median"]})
    assert r.status_code == 202, r.text
    rev = poll(client, f"/api/tasks/{r.json()['task_id']}", lambda t: t["state"] in DONE, timeout=120)
    assert rev["state"] == "COMPLETED", [(e.get("status"), e.get("error")) for e in rev["executions"]]
    assert client.get(f"/api/coding/heads/{pid}").json()["version"] == 2

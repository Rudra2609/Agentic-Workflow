"""Over the real stack (DoD: "integration test over RabbitMQ/Postgres"): API -> Manager on PostgreSQL -> RabbitMQ ->
DocIntelAgent -> RequirementSet -> plan stub -> approval. Replay mode: no network, no keys, no Ollama. Skipped (with
the reason) when ``make infra-up`` has not been run. Redelivery idempotency: the agent's inbox dedups the execution.
"""

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.llm import Gateway
from hmap.core.runtime.discovery import discover
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.system import HmapSystem
from tests.api.helpers import signed_in
from tests.core.bus.conftest import delete_namespace, make_rabbit_bus, new_namespace
from tests.e2e.test_full_stack import CFG, infra, persistence  # noqa: F401  (module fixture re-used)

from .conftest import GOLD

pytestmark = pytest.mark.integration


@pytest.fixture
def client(infra: tuple[str, str], tmp_path: Any) -> Iterator[TestClient]:  # noqa: F811
    url, schema = infra
    ns = new_namespace()
    system = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"),
                        llm=Gateway(Settings(llm_mode="replay")), plugins=discover(), config=CFG,
                        persistence=persistence(url, schema))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c
    asyncio.run(delete_namespace(ns))


def _poll(client: TestClient, url: str, pred: Any, timeout: float = 45.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout on {url}: {body}")


def test_multipart_upload_over_rabbitmq_and_postgres(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "Hostel booking"}).json()["project_id"]
    parts = [("Part A/part_a.pdf", "application/pdf"), ("Part B/part_b.docx",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
             ("Part C/part_c.md", "text/markdown")]
    files = [("files", (name.split("/")[-1], (GOLD / "docs" / "g08_multipart" / name).read_bytes(), media))
             for name, media in parts]
    up = client.post(f"/api/projects/{pid}/documents", files=files, data={"paths": [n for n, _ in parts]})
    assert up.status_code == 201, up.text

    _poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    caps = {t["capability"]: t["state"] for t in client.get(f"/api/projects/{pid}/tasks").json()}
    assert caps["document.extract"] == "COMPLETED" and caps["plan.generate"] == "COMPLETED"
    assert all(state == "CREATED" for c, state in caps.items() if c not in ("document.extract", "plan.generate"))

    rs = client.get(f"/api/doc_intel/requirements/{pid}").json()["requirement_set"]
    folders = {r["source_ref"]["folder"] for r in rs["requirements"]}
    assert folders == {"Part A", "Part B", "Part C"} and rs["total_marks"] == 50
    assert len(rs["evaluation_criteria"]) == 6 and len(rs["requirements"]) >= 6
    events = [e["event_type"] for e in client.get("/api/events", params={"project_id": pid}).json()]
    assert "project.requirements_ready" in events

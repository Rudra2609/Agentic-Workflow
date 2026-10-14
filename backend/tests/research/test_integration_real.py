"""Over the real stack (item 5.16): API -> Manager on PostgreSQL -> RabbitMQ -> ResearchAgent with the pgvector index
(migration 005) -> report, pages, trace and ``research.completed`` in Postgres; deleting the project removes its
index rows. Fake model (rule fallbacks; 8-dim fake embeddings), ``cached`` mode: no network, no keys, no Ollama.
Skipped (with the reason) when ``make infra-up`` has not run."""

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.llm import FakeLLM
from hmap.core.runtime.discovery import discover
from hmap.db import conninfo
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.system import HmapSystem
from tests.api.helpers import signed_in
from tests.core.bus.conftest import delete_namespace, make_rabbit_bus, new_namespace
from tests.e2e.test_full_stack import CFG, infra, persistence  # noqa: F401  (module fixture re-used)

pytestmark = pytest.mark.integration


@pytest.fixture
def stack(infra: tuple[str, str], tmp_path: Any,  # noqa: F811
          monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, str, str]]:
    url, schema = infra
    monkeypatch.setenv("HMAP_RESEARCH_CACHE_DIR", str(tmp_path / "rcache"))
    monkeypatch.setenv("HMAP_RESEARCH_MODE", "cached")
    ns = new_namespace()
    system = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"),
                        llm=FakeLLM(default=None), plugins=discover(), config=CFG, persistence=persistence(url, schema))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c, url, schema
    asyncio.run(delete_namespace(ns))


def poll(client: TestClient, url: str, pred: Any, timeout: float = 90.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout on {url}: {body}")


def _rows(url: str, schema: str, project_id: str) -> tuple[int, int]:
    with psycopg.connect(conninfo(url), options=f"-c search_path={schema},public") as conn:
        total, vectors = conn.execute("SELECT count(*), count(embedding) FROM research_chunks WHERE project_id = %s",
                                      (project_id,)).fetchone()  # type: ignore[misc]
    return int(total), int(vectors)


def test_research_over_rabbitmq_and_postgres_with_the_pgvector_index(stack: tuple[TestClient, str, str]) -> None:
    client, url, schema = stack
    pid = client.post("/api/projects", json={"name": "research"}).json()["project_id"]
    tid = client.post(f"/api/research/runs/{pid}", json={"questions": [
        "How does the asyncio event loop handle many network connections?"]}).json()["task_id"]
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in ("COMPLETED", "FAILED", "DEAD_LETTERED"))
    assert task["state"] == "COMPLETED"
    detail = client.get(f"/api/research/runs/{pid}/{tid}").json()
    assert detail["report"]["evidence"] and detail["report"]["claims"]
    total, vectors = _rows(url, schema, pid)
    assert total > 0 and vectors == total                                         # chunks + embeddings in pgvector
    events = poll(client, f"/api/events?project_id={pid}&limit=500",
                  lambda es: any(e["event_type"] == "research.completed" for e in es))
    assert any(e["event_type"] == "research.completed" and e["data"]["task_id"] == tid for e in events)
    assert client.delete(f"/api/projects/{pid}").status_code in (200, 204)
    deadline = time.time() + 20
    while _rows(url, schema, pid)[0] and time.time() < deadline:
        time.sleep(0.2)
    assert _rows(url, schema, pid) == (0, 0)                                      # project.deleted hook

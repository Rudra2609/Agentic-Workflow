"""Over the real stack (item 6.12): API -> Manager on PostgreSQL -> RabbitMQ -> VerifyAgent -> report + trace ->
``verification.completed`` -> follow-up research + re-check; a forged message on RabbitMQ is refused and lands in
``security_audit`` (migration 006). Fake model (rule fallbacks), ``cached`` research: no network, keys or Ollama.
Skipped (with the reason) when ``make infra-up`` has not run."""

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.contracts import AgentHeartbeat, AgentState, make_envelope
from hmap.core.contracts.common import utcnow
from hmap.core.llm import FakeLLM
from hmap.core.runtime.discovery import discover
from hmap.db import conninfo
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.system import HmapSystem
from tests.api.helpers import signed_in
from tests.core.bus.conftest import delete_namespace, make_rabbit_bus, new_namespace
from tests.e2e.test_full_stack import CFG, infra, persistence  # noqa: F401  (module fixture re-used)
from tests.verify.test_agent_api import DONE, create, store_report, system_of

pytestmark = pytest.mark.integration


@pytest.fixture
def stack(infra: tuple[str, str], tmp_path: Any,  # noqa: F811
          monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, str, str]]:
    url, schema = infra
    monkeypatch.setenv("HMAP_RESEARCH_CACHE_DIR", str(tmp_path / "rcache"))
    monkeypatch.setenv("HMAP_VERIFY_CACHE_DIR", str(tmp_path / "vcache"))
    monkeypatch.setenv("HMAP_RESEARCH_MODE", "cached")
    monkeypatch.setenv("HMAP_VERIFY_MAX_ROUNDS", "1")
    ns = new_namespace()
    system = HmapSystem(bus=make_rabbit_bus(ns), artifacts=LocalFSArtifactStore(tmp_path / "artifacts"),
                        llm=FakeLLM(default=None), plugins=discover(), config=CFG, persistence=persistence(url, schema))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c, url, schema
    asyncio.run(delete_namespace(ns))


def poll(client: TestClient, url: str, pred: Any, timeout: float = 120.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timeout on {url}: {body}")


def _audit(url: str, schema: str, sender: str) -> list[tuple[str, str]]:
    with psycopg.connect(conninfo(url), options=f"-c search_path={schema},public") as conn:
        rows = conn.execute("SELECT rule, reason FROM security_audit WHERE sender = %s AND decision = 'deny'",
                            (sender,)).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def test_verification_and_follow_up_on_rabbitmq_and_postgres(stack: tuple[TestClient, str, str]) -> None:
    client, url, schema = stack
    pid = client.post("/api/projects", json={"name": "verify-real"}).json()["project_id"]
    ref = store_report(client, pid, tamper="This is a stateful authentication mechanism kept in server memory")
    tid = create(client, pid, [ref])
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] in DONE)
    assert task["state"] == "COMPLETED"
    assert [r["artifact_type"] for r in task["executions"][-1]["result_refs"]] == ["verification-report",
                                                                                   "verification-trace"]
    detail = client.get(f"/api/verify/runs/{pid}/{tid}").json()
    c1 = next(c for c in detail["trace"]["claims"] if c["claim_id"] == "C1")
    assert c1["verdict"] == "UNSUPPORTED" and c1["atoms"][0]["row"] == "R1"
    tasks = poll(client, f"/api/projects/{pid}/tasks",
                 lambda ts: len([t for t in ts if t["capability"] == "verify.claims"]) == 2
                 and all(t["state"] in DONE for t in ts), timeout=180)
    assert [t["capability"] for t in tasks].count("research.run") == 1
    events = client.get("/api/events", params={"project_id": pid, "limit": 500}).json()
    assert {e["data"]["round"] for e in events if e["event_type"] == "verification.completed"} == {0, 1}

    # a forged message on the real broker: refused, audited in Postgres, nothing applied
    hb = AgentHeartbeat(agent_id="someone-else", state=AgentState.AVAILABLE, observed_at=utcnow(), available_slots=1,
                        current_execution_ids=[])

    async def forge() -> None:
        await system_of(client).bus.send_reply(make_envelope(hb, sender="intruder-real", correlation_id="c"))

    client.portal.call(forge)  # type: ignore[union-attr]
    deadline = time.time() + 20
    while not _audit(url, schema, "intruder-real") and time.time() < deadline:
        time.sleep(0.1)
    assert _audit(url, schema, "intruder-real") == [("identity", "the message speaks for another agent")]
    sec = client.get("/api/verify/security").json()
    assert any(e["sender"] == "intruder-real" for e in sec["refused"]) and sec["enforced"]

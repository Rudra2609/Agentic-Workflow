"""Operations API (items 4.16, 4.18): owner-only explain / DLQ / replay; replay is explicit (reason, CSRF) and
creates a new execution; overview and failure list."""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.plugins import Plugin
from hmap.core.runtime.discovery import discover
from hmap.system import HmapSystem
from tests.api.helpers import second_client, signed_in
from tests.e2e.test_chaos import FAST, FlakyAgent


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    FlakyAgent.calls = 0
    system = HmapSystem.in_memory(artifact_root=tmp_path / "a", config=FAST,
                                  plugins=[*discover(), Plugin(name="flaky", agents=[FlakyAgent], priority=100)])
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def poll(client: TestClient, url: str, pred: Any, timeout: float = 20.0) -> Any:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        r = client.get(url)
        body = r.json() if r.status_code == 200 else None
        if body is not None and pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout on {url}: {body}")


def test_dlq_explain_and_replay_as_a_new_attempt(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "ops"}).json()["project_id"]
    tid = client.post(f"/api/projects/{pid}/tasks", json={"capability": "flaky.op", "objective": "fetch"}).json()[
        "task_id"]
    dlq = poll(client, "/api/ops/dlq", lambda d: [t for t in d["tasks"] if t["task_id"] == tid])
    [row] = dlq["tasks"]
    assert row["project_name"] == "ops" and row["attempts"] == 1 + FAST.manager.max_retries
    assert row["last_error"]["code"] == "TOOL_TRANSIENT"
    why = client.get(f"/api/ops/explain/{tid}").json()
    assert why["verdict"]["status"] == "dead_lettered" and why["task"]["task_id"] == tid
    failures = client.get("/api/ops/failures").json()
    assert [f["task_id"] for f in failures] == [tid]
    overview = client.get("/api/ops/overview").json()
    assert overview["dead_lettered"] == 1 and overview["links"]["jaeger"].startswith("http")

    # explicit: a reason and the CSRF header are required; other users cannot see or replay it
    assert client.post(f"/api/ops/replay/{tid}", json={"reason": ""}).status_code == 422
    other = second_client(client)
    signed_in(other)
    assert other.get(f"/api/ops/explain/{tid}").status_code == 404
    assert other.post(f"/api/ops/replay/{tid}", json={"reason": "fixed"}).status_code == 404
    assert other.get("/api/ops/dlq").json() == {"tasks": [], "messages": []}
    no_csrf = second_client(client)
    no_csrf.cookies = client.cookies
    no_csrf.headers.pop("X-CSRF-Token", None)
    assert no_csrf.post(f"/api/ops/replay/{tid}", json={"reason": "fixed"}).status_code == 403

    before = len(client.get(f"/api/tasks/{tid}").json()["executions"])
    r = client.post(f"/api/ops/replay/{tid}", json={"reason": "the flaky tool was restarted"})
    assert r.status_code == 200 and r.json()["replay"] == 1
    # the new attempt runs (and, the tool still being flaky, ends in the DLQ again: a new execution each time)
    task = poll(client, f"/api/tasks/{tid}", lambda t: t["state"] == "DEAD_LETTERED" and t["replays"] == 1)
    assert len(task["executions"]) > before
    assert len({e["execution_id"] for e in task["executions"]}) == len(task["executions"])
    events = client.get("/api/events", params={"project_id": pid}).json()
    replayed = [e for e in events if e["event_type"] == "task.replayed"]
    assert replayed and replayed[0]["data"]["reason"] == "the flaky tool was restarted"
    assert replayed[0]["data"]["by"].startswith("user:")
    assert client.post(f"/api/ops/replay/{pid}", json={"reason": "nope"}).status_code == 404
    done = client.post(f"/api/projects/{pid}/tasks", json={"capability": "echo", "objective": "hi"}).json()
    poll(client, f"/api/tasks/{done['task_id']}", lambda t: t["state"] == "COMPLETED")
    assert client.post(f"/api/ops/replay/{done['task_id']}", json={"reason": "why not"}).status_code == 409

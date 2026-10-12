"""Two users on one server: each sees only their own projects, and every attempt by B to reach A's project, tasks,
runs, events, files or controls by id fails — checked against the backend, not the UI."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hmap.api.app import create_app
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in


def poll(client: TestClient, url: str, pred, timeout: float = 10.0):
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = client.get(url).json()
        if pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting on {url}: {body}")


@pytest.fixture
def two_users(tmp_path) -> Iterator[tuple[TestClient, TestClient, str]]:
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts",
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as a:
        b = second_client(a)
        signed_in(a, name="Alice", email="alice@example.test")
        signed_in(b, name="Bob", email="bob@example.test")
        pid = a.post("/api/projects", json={"name": "Alice's secret plan", "goal": "Build a chess club site.",
                                            "auto_approve": True}).json()["project_id"]
        poll(a, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
        b.post("/api/projects", json={"name": "Bob's own"})
        yield a, b, pid


def test_each_user_lists_only_their_projects(two_users) -> None:
    a, b, _pid = two_users
    assert [p["name"] for p in a.get("/api/projects").json()] == ["Alice's secret plan"]
    assert [p["name"] for p in b.get("/api/projects").json()] == ["Bob's own"]
    assert b.get("/api/projects", params={"q": "secret"}).json() == []          # search is scoped too


def test_b_cannot_read_or_control_a_project_by_id(two_users) -> None:
    a, b, pid = two_users
    task_id = a.get(f"/api/projects/{pid}/tasks").json()[0]["task_id"]
    art = a.get(f"/api/projects/{pid}/artifacts").json()[0]
    unknown = b.get("/api/projects/P-does-not-exist")
    attempts = [
        b.get(f"/api/projects/{pid}"),
        b.get(f"/api/projects/{pid}/tasks"),
        b.get(f"/api/projects/{pid}/artifacts"),
        b.get(f"/api/projects/{pid}/artifacts/{art['artifact_id']}"),
        b.get(f"/api/tasks/{task_id}"),
        b.post(f"/api/tasks/{task_id}/cancel", json={}),
        b.patch(f"/api/projects/{pid}", json={"name": "pwned"}),
        b.delete(f"/api/projects/{pid}"),
        b.post(f"/api/projects/{pid}/stop", json={}),
        b.post(f"/api/projects/{pid}/approval", json={"approved": True}),
        b.post(f"/api/projects/{pid}/runs", json={"goal": "do something else"}),
        b.post(f"/api/projects/{pid}/documents", files={"file": ("x.txt", b"x", "text/plain")}),
        b.post(f"/api/projects/{pid}/tasks", json={"capability": "echo", "objective": "x"}),
    ]
    for r in attempts:
        assert r.status_code == 404, (r.request.method, r.request.url, r.status_code, r.text)
    # identical to a project that does not exist: ids cannot be probed
    assert {r.json()["detail"] for r in attempts[:4]} <= {unknown.json()["detail"], "File not found."}
    # nothing changed for Alice
    project = a.get(f"/api/projects/{pid}").json()
    assert project["name"] == "Alice's secret plan" and project["state"] == "COMPLETED" and len(project["runs"]) == 1


def test_b_never_sees_a_events_or_dead_letters(two_users) -> None:
    a, b, pid = two_users
    assert any(e["project_id"] == pid for e in a.get("/api/events").json())
    assert all(e["project_id"] != pid for e in b.get("/api/events").json())
    assert b.get("/api/events", params={"project_id": pid}).json() == []
    for d in b.get("/api/dead-letters").json():
        assert d["project_id"] != pid


def test_b_websocket_carries_no_a_events(two_users) -> None:
    a, b, pid = two_users
    ticket = b.post("/api/auth/ws-ticket").json()["ticket"]
    with pytest.raises(WebSocketDisconnect), b.websocket_connect(f"/api/ws/events?ticket={ticket}&project_id={pid}") \
            as ws:
        ws.receive_json()                                   # asking for A's project closes the socket
    ticket = b.post("/api/auth/ws-ticket").json()["ticket"]
    with b.websocket_connect(f"/api/ws/events?ticket={ticket}") as ws:
        b_pid = b.post("/api/projects", json={"name": "marker"}).json()["project_id"]
        a.post(f"/api/projects/{pid}/runs", json={"goal": "second run, private"})   # A generates events now
        received = []
        for _ in range(500):
            item = ws.receive_json()
            received.append(item)
            if item.get("project_id") == b_pid:
                break
        assert received and all(e.get("project_id") != pid for e in received)


def test_ws_ticket_belongs_to_its_user(two_users) -> None:
    """A ticket is bound to the user who requested it; the socket filters by that user, not by who connects."""
    a, b, pid = two_users
    ticket = a.post("/api/auth/ws-ticket").json()["ticket"]
    with b.websocket_connect(f"/api/ws/events?ticket={ticket}&project_id={pid}") as ws:   # B holds A's ticket
        assert ws.receive_json()["project_id"] in (pid, None)                         # it is A's stream


def test_deleting_a_project_removes_it_and_its_files(two_users) -> None:
    a, _b, pid = two_users
    art = a.get(f"/api/projects/{pid}/artifacts").json()
    assert art and a.get(f"/api/projects/{pid}/artifacts/{art[0]['artifact_id']}").status_code == 200
    r = a.delete(f"/api/projects/{pid}")
    assert r.status_code == 200 and r.json()["files_erased"] == len(art)
    assert a.get(f"/api/projects/{pid}").status_code == 404
    assert a.get(f"/api/projects/{pid}/artifacts/{art[0]['artifact_id']}").status_code == 404
    assert [p["name"] for p in a.get("/api/projects").json()] == []
    assert all(e["project_id"] != pid for e in a.get("/api/events").json() if e["event_type"] != "project.deleted")

"""API (Sprint 1 item 1.15) + the default pipeline: upload -> extract -> plan -> approval -> stubs -> complete."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core.contracts.examples import TASK_GRAPH
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import signed_in


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts",
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))

    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def poll(client: TestClient, url: str, pred, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(url).json()
        if pred(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting on {url}: {body}")


def test_upload_runs_stub_pipeline_with_approval_gate(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "TCP chat"}).json()["project_id"]
    r = client.post(f"/api/projects/{pid}/documents",
                    files={"file": ("assignment.txt", b"The server must accept 10 clients.", "text/plain")})
    assert r.status_code == 201 and r.json()["artifact"]["media_type"] == "text/plain"

    project = poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    assert project["approvals"]
    caps = {t["capability"]: t["state"] for t in client.get(f"/api/projects/{pid}/tasks").json()}
    assert caps["document.extract"] == "COMPLETED" and caps["plan.generate"] == "COMPLETED"

    client.post(f"/api/projects/{pid}/approval", json={"approved": True, "comment": "ok"})
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    tasks = client.get(f"/api/projects/{pid}/tasks").json()
    assert len(tasks) == 2 + len(TASK_GRAPH.tasks) and all(t["state"] == "COMPLETED" for t in tasks)

    events = client.get("/api/events", params={"project_id": pid}).json()
    types = [e["event_type"] for e in events]
    assert "document.uploaded" in types and "approval.requested" in types and "task.completed" in types


def test_validation_and_not_found(client: TestClient) -> None:
    assert client.get("/api/projects/P-nope").status_code == 404
    pid = client.post("/api/projects", json={"name": "x"}).json()["project_id"]
    bad = client.post(f"/api/projects/{pid}/documents", files={"file": ("a.exe", b"MZ", "application/x-msdownload")})
    assert bad.status_code == 415
    empty = client.post(f"/api/projects/{pid}/documents", files={"file": ("a.txt", b"", "text/plain")})
    assert empty.status_code == 400
    assert client.post("/api/projects", json={"name": ""}).status_code == 422


def test_many_documents_in_folders_start_one_run(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "Assignment"}).json()["project_id"]
    r = client.post(f"/api/projects/{pid}/documents",
                    files=[("files", ("brief.pdf", b"%PDF-1.4 part a", "application/pdf")),
                           # browsers often send no type for Markdown: the extension decides
                           ("files", ("data.md", b"# Part B", "application/octet-stream")),
                           ("files", ("notes.txt", b"Part C notes", "text/plain"))],
                    data={"paths": ["Part A/brief.pdf", "Part B/data.md", "../../Part C/notes.txt"]})
    assert r.status_code == 201, r.text
    body = r.json()
    paths = ["Part A/brief.pdf", "Part B/data.md", "Part C/notes.txt"]       # ".." can't climb out
    assert [d["path"] for d in body["documents"]] == paths and body["run"] == 1
    assert [d["folder"] for d in body["documents"]] == ["Part A", "Part B", "Part C"]
    assert [a["media_type"] for a in body["artifacts"]] == ["application/pdf", "text/markdown", "text/plain"]
    project = client.get(f"/api/projects/{pid}").json()
    assert len(project["runs"]) == 1 and project["runs"][0]["documents"] == paths

    tasks = poll(client, f"/api/projects/{pid}/tasks",
                 lambda ts: any(t["capability"] == "document.extract" for t in ts))
    extract = next(t for t in tasks if t["capability"] == "document.extract")
    assert len(extract["artifact_refs"]) == 3
    assert [(d["name"], d["folder"]) for d in extract["inputs"]["documents"]] == [
        ("brief.pdf", "Part A"), ("data.md", "Part B"), ("notes.txt", "Part C")]
    assert "every requirement keeps the folder of its source document" in extract["acceptance_criteria"]
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    uploads = {a["artifact_id"]: a["name"] for a in client.get(f"/api/projects/{pid}/artifacts").json()
               if a["created_by"] == "user"}
    assert sorted(uploads.values()) == sorted(paths)                    # the file list shows each upload's name
    assert {d["artifact_id"]: d["path"] for d in body["documents"]} == uploads


def test_one_unusable_document_rejects_the_whole_upload(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "x"}).json()["project_id"]
    url = f"/api/projects/{pid}/documents"
    bad = client.post(url, files=[("files", ("a.txt", b"ok", "text/plain")),
                                  ("files", ("b.exe", b"MZ", "application/x-msdownload"))])
    assert bad.status_code == 415 and "b.exe" in bad.json()["detail"]
    empty = client.post(url, files=[("files", ("a.txt", b"ok", "text/plain")), ("files", ("c.txt", b"", "text/plain"))])
    assert empty.status_code == 400 and "c.txt" in empty.json()["detail"]
    too_many = [("files", (f"{i}.txt", b"x", "text/plain")) for i in range(21)]
    assert client.post(url, files=too_many).status_code == 400
    mismatched = client.post(url, files=[("files", ("a.txt", b"x", "text/plain"))], data={"paths": ["a.txt", "b.txt"]})
    assert mismatched.status_code == 422
    assert client.post(url).status_code == 400                          # nothing chosen
    assert client.get(f"/api/projects/{pid}").json()["runs"] == []      # no run started, nothing stored


def test_project_can_be_kept_on_this_computer(client: TestClient) -> None:
    private = client.post("/api/projects", json={"name": "Private", "cloud_ok": False}).json()
    assert private["cloud_ok"] is False
    assert client.post("/api/projects", json={"name": "Shared"}).json()["cloud_ok"] is True
    changed = client.patch(f"/api/projects/{private['project_id']}", json={"cloud_ok": True})
    assert changed.status_code == 200 and changed.json()["cloud_ok"] is True
    assert client.patch(f"/api/projects/{private['project_id']}", json={"name": "Renamed"}).json()["cloud_ok"] is True


def test_agents_capabilities_health(client: TestClient) -> None:
    poll(client, "/api/agents", lambda a: len(a) >= 9)
    caps = {c["capability"]: c["status"] for c in client.get("/api/agents/capabilities").json()}
    assert caps["document.extract"] == "stub"
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200


def test_websocket_streams_snapshot_then_live(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "ws"}).json()["project_id"]
    ticket = client.post("/api/auth/ws-ticket").json()["ticket"]
    with client.websocket_connect(f"/api/ws/events?ticket={ticket}") as ws:
        first = ws.receive_json()                     # history snapshot includes project.created
        assert "seq" in first
        client.post(f"/api/projects/{pid}/tasks", json={"capability": "echo", "objective": "hi"})
        seen = set()
        for _ in range(50):
            seen.add(ws.receive_json()["event_type"])
            if "task.completed" in seen:
                break
        assert "task.completed" in seen


def test_llm_usage_shows_key_fingerprints_never_keys(tmp_path) -> None:
    from hmap.core.config import Settings
    from hmap.core.llm.gateway import Gateway

    fake = HmapSystem.in_memory(artifact_root=tmp_path / "a")
    with TestClient(create_app(fake, run_agents=False)) as c:
        signed_in(c)
        assert c.get("/api/llm/usage").json() == {"mode": "fake", "cloud_keys": {}}

    keys = "gsk_test_secret_aaaa1111,gsk_test_secret_bbbb2222"
    settings = Settings.from_env({"HMAP_LLM_MODE": "live", "HMAP_GROQ_API_KEYS": keys,
                                  "HMAP_CLOUD_ROLE_MAP": "coder=groq:llama-x"})
    pooled = HmapSystem.in_memory(artifact_root=tmp_path / "b", llm=Gateway(settings))
    with TestClient(create_app(pooled, run_agents=False)) as c:
        signed_in(c)
        r = c.get("/api/llm/usage")
    body = r.json()
    assert body["mode"] == "live" and len(body["cloud_keys"]) == 2
    assert all(k.startswith("groq:") for k in body["cloud_keys"])
    assert "secret" not in r.text                                   # fingerprints only


def test_auto_approve_project_runs_the_whole_pipeline_without_approval(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "auto", "auto_approve": True}).json()["project_id"]
    client.post(f"/api/projects/{pid}/documents", files={"file": ("a.txt", b"Must accept 10 clients.", "text/plain")})
    project = poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "COMPLETED")
    assert project["auto_approve"] is True
    assert [a["status"] for a in project["approvals"]] == ["approved"]           # recorded, nobody clicked
    assert len(client.get(f"/api/projects/{pid}/tasks").json()) == 7             # extract + plan + 5 plan tasks


def test_stop_button_cancels_the_run_and_a_new_run_can_start(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "stop"}).json()["project_id"]
    client.post(f"/api/projects/{pid}/documents", files={"file": ("a.txt", b"x", "text/plain")})
    poll(client, f"/api/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL")
    r = client.post(f"/api/projects/{pid}/stop", json={"reason": "changed my mind"})
    assert r.status_code == 200 and r.json()["cancelled_tasks"] == 5
    project = r.json()["project"]
    assert project["state"] == "CANCELLED" and project["stopped_reason"] == "changed my mind"
    tasks = client.get(f"/api/projects/{pid}/tasks").json()
    assert {t["state"] for t in tasks if t["capability"] not in ("document.extract", "plan.generate")} == {"CANCELLED"}
    assert client.post(f"/api/projects/{pid}/stop").status_code == 409                # already stopped
    assert client.post(f"/api/projects/{pid}/approval", json={"approved": True}).status_code == 409
    upload = client.post(f"/api/projects/{pid}/documents", files={"file": ("b.txt", b"y", "text/plain")})
    assert upload.status_code == 201 and upload.json()["run"] == 2                   # stopped -> run again
    again = client.post(f"/api/projects/{pid}/documents", files={"file": ("c.txt", b"z", "text/plain")})
    assert again.status_code == 409                                                   # run 2 is still working
    assert client.post("/api/projects/P-nope/stop").status_code == 404

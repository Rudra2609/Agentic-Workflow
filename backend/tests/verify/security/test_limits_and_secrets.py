"""Input limits, localhost-only binding (6.17), project-scoped access (6.14) and no secrets in logs, events,
artifacts or messages (6.15). In memory: no infra."""

import asyncio
import io
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hmap.api.app import create_app
from hmap.core import policy
from hmap.core.contracts import Envelope, TaskProgress, make_envelope
from hmap.core.contracts.envelope import MAX_MESSAGE_BYTES
from hmap.core.llm import FakeLLM
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import second_client, signed_in

ROOT = Path(__file__).resolve().parents[4]
FAKE_GROQ = "gsk_" + "Z9" * 26                              # looks real, is not
FAKE_GEMINI = "AIza" + "Q" * 35
AGENT_SECRET = "s3cr3t-agent-signing-key-for-this-test-only"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("HMAP_GROQ_API_KEYS", FAKE_GROQ)
    monkeypatch.setenv("HMAP_GEMINI_API_KEYS", FAKE_GEMINI)
    system = HmapSystem.in_memory(artifact_root=tmp_path / "artifacts", llm=FakeLLM(default=None),
                                  config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as c:
        signed_in(c)
        yield c


def test_upload_bytes_must_match_the_type(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "u"}).json()["project_id"]
    fake = client.post(f"/api/projects/{pid}/documents",
                       files={"file": ("brief.pdf", b"MZ\x90\x00 not a pdf at all", "application/pdf")})
    assert fake.status_code == 415 and "does not look like" in fake.json()["detail"]
    exe = client.post(f"/api/projects/{pid}/documents", files={"file": ("run.exe", b"MZ", "application/x-msdownload")})
    assert exe.status_code == 415
    binary = client.post(f"/api/projects/{pid}/documents", files={"file": ("notes.txt", b"a\x00b", "text/plain")})
    assert binary.status_code == 415
    ok = client.post(f"/api/projects/{pid}/documents", files={"file": ("notes.txt", b"The server must log in.",
                                                                       "text/plain")})
    assert ok.status_code == 201


def test_write_requests_are_rate_limited(client: TestClient) -> None:
    client.app.state.write_limiter = policy.RateLimiter(rate=0.001, burst=3)  # type: ignore[attr-defined]
    codes = [client.post("/api/projects", json={"name": f"p{i}"}).status_code for i in range(5)]
    assert codes[:3] == [201, 201, 201] and codes[3:] == [429, 429]
    assert client.get("/api/projects").status_code == 200                      # reads are not limited
    other = second_client(client)
    signed_up = other.post("/api/auth/register", json={"name": "B", "email": "b-rl@example.test",
                                                       "password": "correct horse battery staple"})
    assert signed_up.status_code == 201                                        # another client has its own bucket


def test_another_users_project_and_artifacts_are_hidden(client: TestClient) -> None:
    pid = client.post("/api/projects", json={"name": "mine"}).json()["project_id"]
    other = second_client(client)
    signed_in(other)
    for url in (f"/api/projects/{pid}", f"/api/projects/{pid}/tasks", f"/api/verify/runs/{pid}",
                f"/api/research/runs/{pid}", f"/api/projects/{pid}/artifacts"):
        assert other.get(url).status_code in (403, 404), url
    assert other.post(f"/api/verify/runs/{pid}/T-x/follow-up", json={}).status_code == 404
    anonymous = TestClient(client.app)
    anonymous.portal = client.portal  # type: ignore[assignment]
    assert anonymous.get(f"/api/verify/runs/{pid}").status_code == 401


async def test_oversized_message_is_refused() -> None:
    class Ctx:
        async def agent_capabilities(self, agent_id: str) -> list[str] | None:
            return None

        async def execution(self, execution_id: str) -> tuple[str | None, str] | None:
            return None

    p = policy.Policy()
    big = TaskProgress(execution_id="E1", percent=1, summary="x" * (MAX_MESSAGE_BYTES + 10))
    env = make_envelope(big, sender="a1", correlation_id="c", task_id="T1", execution_id="E1")
    assert not await p.check_report(env, big, Ctx())
    assert (await policy.AUDIT.recent(1))[0].rule == "size"


# ---------------------------------------------------------------------------------------- localhost only


def _files(*globs: str) -> list[Path]:
    return [p for g in globs for p in ROOT.glob(g)]


def test_every_listener_binds_to_localhost() -> None:
    for f in _files("infra/*.yml", "infra/**/*.yml"):
        for port in re.findall(r'^\s*-?\s*"?(\d[\d.:]*:\d+)"?', f.read_text(), re.M):
            assert port.startswith("127.0.0.1:"), f"{f.name}: {port}"
        for inline in re.findall(r"ports:\s*\[([^\]]*)\]", f.read_text()):
            assert all(p.strip().strip('"').startswith("127.0.0.1:") for p in inline.split(",")), f"{f.name}"
    for f in _files("scripts/*.sh", "Makefile", "frontend/package.json"):
        text = f.read_text()
        assert "0.0.0.0" not in text, f.name
        for host in re.findall(r"--host(?:name)?[ =](\S+)", text):
            assert host in ("127.0.0.1", "localhost"), f"{f.name}: --host {host}"
    import inspect

    from hmap.obs import metrics

    assert inspect.signature(metrics.serve).parameters["addr"].default == "127.0.0.1"


# ------------------------------------------------------------------------------------------ no secret leaks


def test_no_secret_in_logs_events_artifacts_or_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAP_AGENT_SECRETS", f"kt:{AGENT_SECRET}")
    monkeypatch.setenv("HMAP_GROQ_API_KEYS", FAKE_GROQ)
    monkeypatch.setenv("HMAP_GEMINI_API_KEYS", FAKE_GEMINI)
    monkeypatch.setenv("HMAP_LOG_LEVEL", "DEBUG")
    from hmap.core.config import Settings

    logs = io.StringIO()                       # create_app points the logger at sys.stderr: make that our buffer
    monkeypatch.setattr(sys, "stderr", logs)
    signer = policy.install(keyring=policy.Keyring.from_settings(Settings.from_env()))
    sent: list[Envelope] = []
    try:
        system = HmapSystem.in_memory(artifact_root=tmp_path / "a", llm=FakeLLM(default=None),
                                      config=SystemConfig(heartbeat_s=0.2, watchdog_interval_s=0.05))
        original = system.bus.send_reply

        async def spy(env: Envelope) -> None:
            sent.append(env)
            await original(env)

        system.bus.send_reply = spy  # type: ignore[method-assign]
        with TestClient(create_app(system, run_agents=True)) as c:
            signed_in(c)
            pid = c.post("/api/projects", json={"name": "s"}).json()["project_id"]
            c.post(f"/api/projects/{pid}/documents", files={"file": ("brief.txt", b"The server must accept 10 "
                                                                     b"clients and broadcast every message.",
                                                                     "text/plain")})
            for _ in range(200):
                if any(t["state"] == "COMPLETED" for t in c.get(f"/api/projects/{pid}/tasks").json()):
                    break
                asyncio.run(asyncio.sleep(0.02))
            events = c.get("/api/events", params={"project_id": pid, "limit": 500}).text
            agents = c.get("/api/agents").text
        tokens = [signer.token(e.sender.agent_id) for e in sent]
        assert sent and tokens
        assert "llm" in logs.getvalue() or "agent" in logs.getvalue()   # the log really was captured
        blobs: dict[str, str] = {"logs": logs.getvalue(), "events": events, "agents": agents,
                                 "messages": "\n".join(e.model_dump_json() for e in sent),
                                 "artifacts": "\n".join(p.read_text(errors="ignore")
                                                        for p in (tmp_path / "a").rglob("*") if p.is_file())}
        secrets_: list[str] = [FAKE_GROQ, FAKE_GEMINI, AGENT_SECRET, *tokens]
        for where, blob in blobs.items():
            leaked = [policy.fingerprint(s) for s in secrets_ if s in blob]
            assert not leaked, f"secret(s) {leaked} found in {where}"
        assert all(e.auth for e in sent)                                 # every message signed, token absent
    finally:
        policy.install(keyring=policy.Keyring.from_settings())

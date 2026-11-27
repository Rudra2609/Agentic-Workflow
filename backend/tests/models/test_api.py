from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hmap.agents.models import router as router_mod
from hmap.agents.models.model import RouteRecord
from hmap.agents.models.plugin import PLUGIN
from hmap.agents.models.router import ModelRouter
from hmap.agents.models.store import MemoryModelStore
from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.contracts.domain import RouteDecision
from hmap.core.llm import FakeLLM, Gateway
from hmap.core.runtime.host import make_llm
from hmap.system import HmapSystem
from tests.api.helpers import signed_in


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> MemoryModelStore:
    fresh = MemoryModelStore()
    monkeypatch.setattr(router_mod, "MEMORY_STORE", fresh)
    from hmap.agents.models import api

    monkeypatch.setattr(api, "MEMORY_STORE", fresh)
    return fresh


@pytest.fixture
def client(tmp_path: Path, store: MemoryModelStore, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")      # nothing answers: the snapshot is used
    system = HmapSystem.in_memory(artifact_root=tmp_path / "a", llm=FakeLLM(), plugins=[PLUGIN])
    with TestClient(create_app(system, run_agents=False)) as c:
        signed_in(c)
        yield c


def test_needs_sign_in(tmp_path: Path, store: MemoryModelStore) -> None:
    system = HmapSystem.in_memory(artifact_root=tmp_path / "a", llm=FakeLLM(), plugins=[PLUGIN])
    with TestClient(create_app(system, run_agents=False)) as c:
        assert c.get("/api/models/registry").status_code == 401
        assert c.get("/api/models/routes").status_code == 401


def test_models_hardware_and_flags(client: TestClient) -> None:
    body = client.get("/api/models/registry").json()
    ids = {m["spec"]["id"]: m for m in body["models"]}
    assert ids["qwen3.5:9b"]["spec"]["status"] == "available" and ids["qwen3.5:9b"]["source"] == "snapshot"
    assert ids["qwen3.5:9b"]["spec"]["tok_s"] > 0                     # the newest speed run (bench/results/speed.json)
    assert body["ollama_up"] is False
    assert client.post("/api/models/registry/qwen3.5:4b/disable").json()["status"] == "disabled"
    assert client.post("/api/models/registry/qwen3.5:9b/pin").json()["pinned"] is True
    assert client.post("/api/models/registry/nope/pin").status_code == 404
    again = {m["spec"]["id"]: m for m in client.post("/api/models/registry/sync").json()["models"]}
    assert again["qwen3.5:4b"]["spec"]["status"] == "disabled" and again["qwen3.5:9b"]["pinned"]
    hw = client.get("/api/models/hardware").json()
    assert hw["hardware"]["total_gb"] > 0 and {r["ram_gb"] for r in hw["sizing"]} == {8, 16, 24, 48}
    assert any(f["model"] == "qwen3.5:9b" for f in hw["feasibility"])


def test_pull_only_tier_models_and_only_the_command_by_default(client: TestClient) -> None:
    assert client.post("/api/models/pull", json={"model": "evil; rm -rf /"}).status_code == 400
    r = client.post("/api/models/pull", json={"model": "qwen3.5:4b"}).json()
    assert r["started"] is False and r["command"].endswith("ollama pull qwen3.5:4b")


def test_routes_bench_finetune(client: TestClient, store: MemoryModelStore) -> None:
    import asyncio

    rec = RouteRecord(decision=RouteDecision(role="coder", model="gpt-oss-120b", backend="groq", reason="x"),
                      plugin="coding", chain=["groq:gpt-oss-120b"], rule="rules", answered_by="groq:gpt-oss-120b",
                      ok=True, attempts=2, rate_limited=1)
    asyncio.run(store.add_routes([rec]))
    body = client.get("/api/models/routes", params={"role": "coder"}).json()
    assert body["summary"] == {"decisions": 1, "answered_by": {"groq": 1}, "failed": 0, "rules": {"rules": 1},
                               "rate_limited": 1, "attempts": 2}
    assert client.get("/api/models/routes", params={"role": "fast"}).json()["routes"] == []
    assert "rows" in client.get("/api/models/bench").json()
    assert client.get("/api/models/bench/no-such-set").status_code == 404
    assert "runs" in client.get("/api/models/finetune").json()


def test_routes_since_is_the_poll(client: TestClient, store: MemoryModelStore) -> None:
    import asyncio

    first = client.get("/api/models/routes").json()
    assert first["routes"] == [] and first["now"]
    rec = RouteRecord(decision=RouteDecision(role="fast", model="m", backend="groq"), plugin="research",
                      at="2999-01-01T00:00:00+00:00")
    asyncio.run(store.add_routes([rec]))
    assert [r["id"] for r in client.get("/api/models/routes", params={"since": first["now"]}).json()["routes"]] \
        == [rec.id]


def test_both_gateway_builders_attach_the_router() -> None:
    """Trap T3: the in-process system and the agents' own process (split mode) both get the slot."""
    s = Settings(router="on", llm_mode="replay", cloud_role_map={})
    system = HmapSystem.from_settings(s, plugins=[PLUGIN])
    assert isinstance(system.llm, Gateway) and isinstance(system.llm.route, ModelRouter)
    assert system.llm.route.enabled and system.llm.route.scheduler is not None
    split = make_llm(s, [PLUGIN])
    assert isinstance(split, Gateway) and isinstance(split.route, ModelRouter)
    assert make_llm(s).route is None                                           # type: ignore[attr-defined]

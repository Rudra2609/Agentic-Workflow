import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from hmap.agents.models.backends import CloudPoolBackend, OllamaBackend, OpenAILocalBackend, build_backends
from hmap.agents.models.registry import ModelRegistry
from hmap.agents.models.store import MemoryModelStore
from hmap.core.config import Settings
from hmap.core.llm import CloudRouter, Gateway
from hmap.core.llm.providers.base import ChatRequest
from tests.core.llm.test_key_pool import GROQ_KEYS, FakeClock, FakeCloud

from .helpers import FakeOllama, FakeOpenAILocal


class Answer(BaseModel):
    value: str


@pytest.fixture
def keyed() -> Settings:
    return Settings(groq_api_keys=GROQ_KEYS, role_map={"reasoner": "qwen3.5:9b", "fast": "qwen3.5:4b"},
                    cloud_role_map={"reasoner": [("groq", "gpt-oss-120b"), ("gemini", "gemini-x")],
                                    "fast": [("groq", "gpt-oss-20b")]})


async def test_sync_from_ollama(keyed: Settings, tmp_path: Path) -> None:
    ollama = FakeOllama(resident={"qwen3.5:9b": 5_770_000_000})
    store = MemoryModelStore()
    reg = ModelRegistry(keyed, store, client=ollama.client(), models_dir=tmp_path)
    rows = {r.spec.id: r for r in await reg.sync()}
    assert reg.ollama_up
    nine = rows["qwen3.5:9b"]
    assert (nine.spec.status, nine.spec.quant, nine.digest, nine.spec.ctx) == ("installed", "Q4_K_M", "sha256:aaa",
                                                                               262144)
    assert nine.resident_gb == pytest.approx(5.77) and nine.spec.roles_ok == ["reasoner"]
    assert nine.details["block_count"] == 32                          # the GGUF snapshot fills the architecture
    assert rows["nomic-embed-text:latest"].spec.roles_ok == ["embed"]
    assert rows["qwen3:8b"].spec.status == "missing"                   # on the snapshot, no longer installed
    assert rows["groq:gpt-oss-120b"].spec.status == "available"        # keys present
    assert rows["gemini:gemini-x"].spec.status == "missing"            # no Gemini keys
    assert set(await reg.installed_local()) == {"qwen3.5:9b", "qwen3.5:4b", "nomic-embed-text:latest"}


async def test_ollama_down_falls_back_to_the_snapshot(keyed: Settings) -> None:
    ollama = FakeOllama()
    ollama.up = False
    reg = ModelRegistry(keyed, MemoryModelStore(), client=ollama.client())
    rows = {r.spec.id: r for r in await reg.sync()}
    assert not reg.ollama_up and "not running" in reg.last_error
    assert rows["qwen3.5:9b"].spec.status == "available" and rows["qwen3.5:9b"].source == "snapshot"


async def test_pin_and_disable_survive_a_sync(keyed: Settings, tmp_path: Path) -> None:
    ollama = FakeOllama()
    store = MemoryModelStore()
    reg = ModelRegistry(keyed, store, client=ollama.client(), models_dir=tmp_path)
    await reg.sync()
    assert await store.set_flags("qwen3.5:4b", status="disabled")
    assert await store.set_flags("qwen3.5:9b", pinned=True)
    assert not await store.set_flags("nope", pinned=True)
    rows = {r.spec.id: r for r in await reg.sync()}
    assert rows["qwen3.5:4b"].spec.status == "disabled" and rows["qwen3.5:9b"].pinned
    assert "qwen3.5:4b" not in await reg.installed_local()


async def test_mlx_and_llamacpp_servers_are_registered(tmp_path: Path) -> None:
    ollama, mlx = FakeOllama(), FakeOpenAILocal(["qwen3.5-4b-verify-lora"])
    s = Settings(mlx_base_url="http://mlx.local/v1", cloud_role_map={})
    reg = ModelRegistry(s, MemoryModelStore(), client=mlx.client(), models_dir=tmp_path)
    reg.settings = s.model_copy(update={"ollama_base_url": "http://ollama.invalid"})
    rows = {r.spec.id: r for r in await reg.sync()}
    assert rows["mlx:qwen3.5-4b-verify-lora"].spec.backend == "mlx"
    del ollama


async def test_same_request_works_on_every_backend(keyed: Settings) -> None:
    """Item 11.3: one structured request through Ollama, an MLX server, a llama.cpp server and the key pool."""
    ollama, mlx, llama, cloud = FakeOllama(), FakeOpenAILocal(["m"]), FakeOpenAILocal(["l"]), FakeCloud()
    router = CloudRouter.from_settings(keyed, client=cloud.client(), clock=FakeClock())
    assert router is not None
    backends = {"ollama": OllamaBackend("http://o", client=ollama.client()),
                "mlx": OpenAILocalBackend("mlx", "http://mlx/v1", client=mlx.client()),
                "llamacpp": OpenAILocalBackend("llamacpp", "http://llama/v1", client=llama.client()),
                "cloud": CloudPoolBackend(router)}
    models = {"ollama": "qwen3.5:9b", "mlx": "mlx:m", "llamacpp": "llamacpp:l", "cloud": "groq:gpt-oss-120b"}
    schema = Answer.model_json_schema()
    for name, backend in backends.items():
        health = await backend.health()
        assert health.ok, name
        req = ChatRequest(model=models[name], messages=[{"role": "system", "content": "be brief"},
                                                        {"role": "user", "content": "q"}], role="reasoner",
                          json_schema=schema, max_tokens=50)
        resp = await backend.chat(req)
        assert resp.text, name
        if name != "cloud":
            Answer.model_validate_json(resp.text)
    assert mlx.bodies[0]["model"] == "m" and llama.bodies[0]["model"] == "l"   # the registry prefix is removed
    # one system message, the schema hint inside it (Qwen's template; mlx_lm.server rejects a second one)
    assert [m["role"] for m in mlx.bodies[0]["messages"]] == ["system", "user"]
    assert mlx.bodies[0]["messages"][0]["content"].startswith("Respond with a single JSON object")
    assert mlx.bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}   # else Qwen 3.5 thinks: empty answer
    assert json.loads(cloud.requests[0].content)["model"] == "gpt-oss-120b"
    # a backend can be the router's local provider in a real gateway call
    gw = Gateway(keyed.model_copy(update={"cloud_role_map": {}}), mode="live")
    from hmap.core.plugins import RoutePlan

    class Fixed:
        def decide(self, q: object) -> RoutePlan:
            return RoutePlan(cloud_routes=[], local_model="mlx:m", local=backends["mlx"])

        def observe(self, *a: object) -> None: ...

    gw._shared.route = Fixed()  # type: ignore[assignment]
    out = await gw.generate("reasoner", [{"role": "user", "content": "q"}], schema=Answer)
    assert out.parsed == Answer(value="local-server") and out.usage.provider == "mlx"


async def test_health_reports_down_backends() -> None:
    ollama = FakeOllama()
    ollama.up = False
    b = OllamaBackend("http://o", client=ollama.client())
    assert not (await b.health()).ok
    ollama.up = True
    assert not (await b.health()).ok            # cached for 10 s
    assert (await b.health(fresh=True)).ok


def test_build_backends(keyed: Settings) -> None:
    s = keyed.model_copy(update={"mlx_base_url": "http://mlx/v1"})
    assert set(build_backends(s)) == {"ollama", "mlx"}

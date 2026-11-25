"""The ``llm_provider`` strategy slot in the gateway (Sprint 11, Member 1 change for Member 11's router)."""

import json
from typing import Any

import pytest

from hmap.core.config import Settings
from hmap.core.errors import ModelTransientError
from hmap.core.llm import ChatRequest, CloudRouter, FakeLLM, Gateway, LLMResponse, LLMUsage, OllamaProvider
from hmap.core.plugins import NoRouting, Plugin, RouteOutcome, RoutePlan, RouteQuery
from hmap.core.runtime.host import route_strategy

from .conftest import FakeOllamaServer
from .test_key_pool import GEMINI_KEYS, GEMINI_URL, GROQ_KEYS, GROQ_URL, MSG, FakeClock, FakeCloud


class Recorder:
    """A strategy that returns a fixed plan and records what it was told."""

    def __init__(self, plan: RoutePlan | None = None, *, fail: bool = False) -> None:
        self.plan = plan
        self.fail = fail
        self.queries: list[RouteQuery] = []
        self.outcomes: list[RouteOutcome] = []
        self.attempts: list[tuple[str, str, str, str]] = []
        self.configured: Settings | None = None

    def configure(self, settings: Settings) -> None:
        self.configured = settings

    def decide(self, query: RouteQuery) -> RoutePlan | None:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("router bug")
        return self.plan

    def observe(self, query: RouteQuery, plan: RoutePlan | None, outcome: RouteOutcome) -> None:
        self.outcomes.append(outcome)
        if self.fail:
            raise RuntimeError("observer bug")

    def observe_attempt(self, provider: str, model: str, role: str, outcome: str, latency_s: float) -> None:
        self.attempts.append((provider, model, role, outcome))


class OtherLocal:
    name = "mlx"

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(text="from-mlx", usage=LLMUsage(model=request.model, provider=self.name))


@pytest.fixture
def two_providers(settings: Settings) -> Settings:
    return settings.model_copy(update={
        "groq_api_keys": Settings(groq_api_keys=GROQ_KEYS).groq_api_keys,
        "gemini_api_keys": Settings(gemini_api_keys=GEMINI_KEYS).gemini_api_keys,
        "cloud_role_map": {"coder": [("groq", "llama-x"), ("gemini", "gemini-x")]},
        "role_map": {"reasoner": "qwen3.5:9b", "coder": "qwen3.5:9b"}})


def gateway(s: Settings, server: FakeOllamaServer, cloud: FakeCloud | None, route: Any, **kw: Any) -> Gateway:
    router = CloudRouter.from_settings(s, client=cloud.client(), clock=FakeClock()) if cloud is not None else None
    return Gateway(s, local=OllamaProvider(s.ollama_base_url, server.client()), cloud_router=router, route=route,
                   mode=kw.pop("mode", "live"), **kw)


async def test_no_plan_keeps_the_role_maps(two_providers: Settings, server: FakeOllamaServer) -> None:
    cloud = FakeCloud()
    rec = Recorder(None)
    gw = gateway(two_providers, server, cloud, rec).for_plugin("coding")
    resp = await gw.generate("coder", MSG, max_tokens=100)
    assert resp.usage.provider == "groq" and cloud.urls == [GROQ_URL]
    q = rec.queries[0]
    assert (q.role, q.plugin, q.default_model, q.cloud_allowed) == ("coder", "coding", "qwen3.5:9b", True)
    assert q.default_routes == (("groq", "llama-x"), ("gemini", "gemini-x"))
    assert q.pool == {"groq": 3, "gemini": 1} and q.est_tokens >= 100
    assert rec.outcomes[0].ok and rec.outcomes[0].provider == "groq"
    assert rec.attempts == [("groq", "llama-x", "coder", "ok")]
    assert gw.route is rec


async def test_plan_reorders_cloud_routes(two_providers: Settings, server: FakeOllamaServer) -> None:
    cloud = FakeCloud()
    gw = gateway(two_providers, server, cloud, Recorder(RoutePlan(cloud_routes=[("gemini", "gemini-x")])))
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "gemini" and cloud.urls == [GEMINI_URL]
    assert json.loads(cloud.requests[0].content)["model"] == "gemini-x"


async def test_plan_can_route_an_unmapped_role_to_the_cloud(two_providers: Settings, server: FakeOllamaServer) -> None:
    cloud = FakeCloud()
    gw = gateway(two_providers, server, cloud, Recorder(RoutePlan(cloud_routes=[("groq", "small")])))
    resp = await gw.generate("reasoner", MSG)       # reasoner is not in the cloud role map
    assert resp.usage.provider == "groq" and json.loads(cloud.requests[0].content)["model"] == "small"


async def test_empty_routes_mean_no_cloud_and_local_model_override(two_providers: Settings,
                                                                   server: FakeOllamaServer) -> None:
    cloud = FakeCloud()
    gw = gateway(two_providers, server, cloud, Recorder(RoutePlan(cloud_routes=[], local_model="qwen3.5:4b")))
    resp = await gw.generate("coder", MSG)
    assert cloud.requests == [] and resp.usage.provider == "ollama"
    assert server.bodies[0]["model"] == "qwen3.5:4b"


async def test_plan_local_provider_replaces_ollama(two_providers: Settings, server: FakeOllamaServer) -> None:
    other = OtherLocal()
    rec = Recorder(RoutePlan(cloud_routes=[], local_model="adapter-x", local=other))
    gw = gateway(two_providers, server, None, rec)
    resp = await gw.generate("coder", MSG)
    assert resp.text == "from-mlx" and other.requests[0].model == "adapter-x" and server.bodies == []
    assert rec.outcomes[0].provider == "mlx"


async def test_cloud_ok_false_still_wins_over_a_plan(two_providers: Settings, server: FakeOllamaServer) -> None:
    cloud = FakeCloud()
    rec = Recorder(RoutePlan(cloud_routes=[("groq", "llama-x")]))
    gw = gateway(two_providers, server, cloud, rec).local_only()
    await gw.generate("coder", MSG)
    assert cloud.requests == [] and rec.queries[0].cloud_allowed is False


async def test_a_broken_router_never_breaks_a_call(two_providers: Settings, server: FakeOllamaServer) -> None:
    rec = Recorder(fail=True)
    gw = gateway(two_providers, server, None, rec)
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "ollama" and server.bodies[0]["model"] == "qwen3.5:9b"


class BrokenLocal:
    name = "broken"

    async def chat(self, request: ChatRequest) -> LLMResponse:
        raise ModelTransientError("down")


async def test_failed_call_is_observed(two_providers: Settings, server: FakeOllamaServer) -> None:
    rec = Recorder(RoutePlan(cloud_routes=[], local=BrokenLocal()))
    gw = gateway(two_providers, server, None, rec)
    with pytest.raises(ModelTransientError):
        await gw.generate("coder", MSG)
    assert rec.outcomes and rec.outcomes[0].ok is False and rec.outcomes[0].provider == "error"


async def test_replay_and_fake_never_ask_the_router(two_providers: Settings, server: FakeOllamaServer) -> None:
    rec = Recorder(RoutePlan(cloud_routes=[], local_model="qwen3.5:4b"))
    recorder = gateway(two_providers.model_copy(update={"cloud_role_map": {}}), server, None, rec,
                       mode="record").for_plugin("doc_intel")
    first = await recorder.generate("reasoner", MSG)
    asked = len(rec.queries)
    replay = Gateway(two_providers, mode="replay", route=rec).for_plugin("doc_intel")
    again = await replay.generate("reasoner", MSG)
    assert again.text == first.text and len(rec.queries) == asked      # the model is not in the replay key
    fake = Gateway(two_providers, mode="fake", fake=FakeLLM(), route=rec)
    await fake.generate("reasoner", MSG)
    assert len(rec.queries) == asked


def test_route_strategy_picks_highest_priority_and_configures(settings: Settings) -> None:
    low, high = Recorder(), Recorder()
    plugins = [Plugin(name="a", provides={"llm_provider": low}, priority=10),
               Plugin(name="b", provides={"llm_provider": high}, priority=100),
               Plugin(name="c", provides={"llm_provider": None})]
    assert route_strategy(plugins, settings) is high and high.configured is settings and low.configured is None
    assert route_strategy([Plugin(name="c")], settings) is None
    assert route_strategy([Plugin(name="d", provides={"llm_provider": NoRouting})], settings).decide(
        RouteQuery("fast", "x", 1, 1, False, False, None, ())) is None

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from hmap.core.config import LLMMode, Settings
from hmap.core.errors import ModelTransientError
from hmap.core.llm import (
    ChatRequest,
    ClassifyQuestion,
    FakeLLM,
    Gateway,
    LLMClient,
    LLMConfigError,
    LLMResponse,
    LLMUsage,
    OllamaProvider,
    OpenAICompatProvider,
    Role,
    build_llm,
    resolve_model,
)

from .conftest import FakeOllamaServer


class Answer(BaseModel):
    value: str


class CountingLocal:
    """A non-network local provider that tracks how many chats run at once."""

    name = "counting"

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> LLMResponse:
        self.requests.append(request)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return LLMResponse(text="ok", usage=LLMUsage(model=request.model, provider=self.name))

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]


def live(settings: Settings, server: FakeOllamaServer, mode: LLMMode = "live", **kwargs: Any) -> Gateway:
    return Gateway(settings, local=OllamaProvider(settings.ollama_base_url, server.client()), mode=mode, **kwargs)


def test_gateway_satisfies_llm_client_protocol(settings: Settings) -> None:
    client: LLMClient = Gateway(settings)
    fake: LLMClient = FakeLLM()
    assert client is not None and fake is not None


async def test_live_structured_generate(settings: Settings, server: FakeOllamaServer) -> None:
    server.replies = ["not json", '{"value": "fixed"}']
    gw = live(settings, server).for_plugin("doc_intel")
    resp = await gw.generate("reasoner", [{"role": "user", "content": "q"}], schema=Answer)
    assert resp.parsed == Answer(value="fixed")
    assert [b["format"]["title"] for b in server.bodies] == ["Answer", "Answer"]
    assert all(b["think"] is False for b in server.bodies)
    assert not settings.llm_cache_dir.exists()  # live never writes the cache


async def test_record_then_replay_is_identical_with_zero_http(settings: Settings, server: FakeOllamaServer) -> None:
    server.replies = ["garbage", '{"value": "42"}']
    recorder = live(settings, server, mode="record").for_plugin("doc_intel")
    msgs = [{"role": "user", "content": "what is it?"}]
    recorded = await recorder.generate("reasoner", msgs, schema=Answer, seed=1)
    vectors = await recorder.embed(["alpha", "beta"])
    n_http = len(server.requests)
    assert n_http == 3

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network call in replay: {request.url}")

    replay_settings = settings.model_copy(update={"role_map": {}, "llm_mode": "replay"})
    replay = Gateway(replay_settings,
                     local=OllamaProvider("http://x", httpx.AsyncClient(transport=httpx.MockTransport(no_network))))
    replay = replay.for_plugin("doc_intel")
    replayed = await replay.generate("reasoner", msgs, schema=Answer, seed=1)
    assert replayed.text == recorded.text and replayed.parsed == recorded.parsed
    assert replayed.usage.input_tokens == recorded.usage.input_tokens
    assert replayed.usage.cached is True
    assert await replay.embed(["alpha", "beta"]) == vectors
    assert len(server.requests) == n_http
    # both attempts (invalid + repair) and the embedding were recorded under the plug-in folder
    assert len(list((settings.llm_cache_dir / "doc_intel").glob("*/*.json"))) == 3


async def test_replay_mode_never_builds_a_provider(settings: Settings) -> None:
    gw = Gateway(settings.model_copy(update={"llm_mode": "replay"}))
    assert gw._shared._local is None
    with pytest.raises(Exception, match="replay miss"):
        await gw.generate("reasoner", [{"role": "user", "content": "x"}])
    assert gw._shared._local is None


def test_role_aliasing_and_fallback() -> None:
    one = {"reasoner": "qwen3:8b", "embed": "nomic-embed-text"}
    assert resolve_model(one, "judge") == "qwen3:8b"
    assert resolve_model(one, "coder") == "qwen3:8b"
    assert resolve_model(one, "classify") == "qwen3:8b"
    assert resolve_model({**one, "fast": "llama3.2:3b"}, "classify") == "llama3.2:3b"
    assert resolve_model({**one, "judge": "llama3.1:8b"}, "judge") == "llama3.1:8b"
    with pytest.raises(LLMConfigError, match="HMAP_ROLE_MAP"):
        resolve_model({"embed": "nomic-embed-text"}, "judge")


async def test_roles_alias_one_model_on_the_wire(settings: Settings, server: FakeOllamaServer) -> None:
    gw = live(settings, server)
    roles: list[Role] = ["fast", "judge", "coder", "reasoner"]
    for role in roles:
        await gw.generate(role, [{"role": "user", "content": role}])
    assert {b["model"] for b in server.bodies} == {"qwen3:8b"}
    assert "/api/generate" not in server.paths()  # one model: no unloads


async def test_semaphore_limits_concurrency(settings: Settings) -> None:
    local = CountingLocal()
    gw = Gateway(settings.model_copy(update={"llm_max_concurrency": 2}), local=local)
    await asyncio.gather(*(gw.generate("reasoner", [{"role": "user", "content": str(i)}]) for i in range(6)))
    assert local.peak == 2 and len(local.requests) == 6

    serial = CountingLocal()
    gw1 = Gateway(settings, local=serial)
    await asyncio.gather(*(gw1.generate("reasoner", [{"role": "user", "content": str(i)}]) for i in range(4)))
    assert serial.peak == 1


async def test_classify_one_answer_per_question(settings: Settings, server: FakeOllamaServer) -> None:
    server.replies = [json.dumps({"relevant": {"answer": "YES", "confidence": 0.8},
                                  "category": {"answer": "bug", "confidence": 0.6},
                                  "severity": {"answer": "4", "confidence": 1.5}})]
    gw = live(settings, server)
    questions = [ClassifyQuestion(name="relevant", kind="bool"),
                 ClassifyQuestion(name="category", kind="choice", options=["bug", "feature"],
                                  criteria={"bug": "something broken"}),
                 ClassifyQuestion(name="severity", kind="score")]
    answers = await gw.classify("the login button crashes the app", questions)
    assert [a.name for a in answers] == ["relevant", "category", "severity"]
    assert [a.answer for a in answers] == ["yes", "bug", "4"]
    assert answers[0].probabilities == {"yes": 0.8, "no": 0.2}
    assert answers[2].probabilities == {"4": 1.0}
    body = server.bodies[0]
    assert body["options"]["temperature"] == 0.0
    props = body["format"]["properties"]
    assert props["relevant"]["properties"]["answer"]["enum"] == ["yes", "no"]
    assert props["category"]["properties"]["answer"]["enum"] == ["bug", "feature"]
    assert props["severity"]["properties"]["answer"]["enum"] == ["1", "2", "3", "4", "5"]
    assert "something broken" in body["messages"][-1]["content"]


async def test_fake_mode_delegates_to_fake(settings: Settings) -> None:
    fake = FakeLLM().on_role("fast", "quick").on_schema(Answer, Answer(value="v")).on_classify("ok", "no")
    gw = build_llm(settings.model_copy(update={"llm_mode": "fake"}), plugin="x", fake=fake)
    assert (await gw.generate("fast", [{"role": "user", "content": "hi"}])).text == "quick"
    resp = await gw.generate("reasoner", [{"role": "user", "content": "hi"}], schema=Answer)
    assert resp.parsed == Answer(value="v")
    assert [a.answer for a in await gw.classify("s", [ClassifyQuestion(name="ok", kind="bool")])] == ["no"]
    assert len(await gw.embed(["a"])) == 1
    assert len(fake.calls) == 2 and not settings.llm_cache_dir.exists()


# ---------------------------------------------------------------------- optional cloud provider
def cloud_transport(statuses: list[int], seen: list[httpx.Request], retry_after: str = "1") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = statuses[min(len(seen) - 1, len(statuses) - 1)]
        if status == 429:
            return httpx.Response(429, headers={"retry-after": retry_after}, json={"error": "rate"})
        return httpx.Response(status, json={"model": "llama-3.3-70b", "choices": [{"message": {"content": "cloud"}}],
                                            "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    return httpx.MockTransport(handler)


def make_cloud(statuses: list[int], seen: list[httpx.Request], sleeps: list[float],
               retry_after: str = "1") -> OpenAICompatProvider:
    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return OpenAICompatProvider("https://api.groq.test/openai/v1", "gsk_SECRET",
                                httpx.AsyncClient(transport=cloud_transport(statuses, seen, retry_after)),
                                model_map={"judge": "llama-3.3-70b"}, sleep=fake_sleep)


async def test_cloud_not_used_unless_allowed(settings: Settings, server: FakeOllamaServer) -> None:
    seen: list[httpx.Request] = []
    gw = live(settings, server, cloud=make_cloud([200], seen, []))
    resp = await gw.generate("judge", [{"role": "user", "content": "x"}])
    assert resp.usage.provider == "ollama" and not seen
    resp = await gw.generate("judge", [{"role": "user", "content": "x"}], allow_cloud=True)
    assert resp.text == "cloud" and resp.usage.provider == "cloud" and len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer gsk_SECRET"
    assert str(seen[0].url) == "https://api.groq.test/openai/v1/chat/completions"
    assert json.loads(seen[0].content)["model"] == "llama-3.3-70b"
    bound = gw.for_plugin("research", cloud_ok=True)
    assert (await bound.generate("judge", [{"role": "user", "content": "x"}])).usage.provider == "cloud"
    assert (await bound.generate("judge", [{"role": "user", "content": "x"}], allow_cloud=False)).text == "hello"
    local_only = gw.for_plugin("private", cloud_ok=False)  # a local-only project cannot be overridden per call
    assert (await local_only.generate("judge", [{"role": "user", "content": "x"}], allow_cloud=True)).text == "hello"
    off = live(settings.model_copy(update={"cloud_ok": False}), server, cloud=make_cloud([200], seen, []))
    assert (await off.generate("judge", [{"role": "user", "content": "x"}], allow_cloud=True)).text == "hello"
    assert len(seen) == 2


async def test_cloud_429_retry_after_then_fallback_to_local(settings: Settings, server: FakeOllamaServer) -> None:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    gw = live(settings, server, cloud=make_cloud([429], seen, sleeps, retry_after="1.5"), cloud_ok=True)
    resp = await gw.generate("judge", [{"role": "user", "content": "x"}])
    assert len(seen) == 3  # 1 + 2 bounded retries
    assert sleeps == [1.5, 1.5]
    assert resp.text == "hello" and resp.usage.provider == "ollama"


async def test_cloud_429_then_success(settings: Settings, server: FakeOllamaServer) -> None:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    gw = live(settings, server, cloud=make_cloud([429, 200], seen, sleeps), cloud_ok=True)
    resp = await gw.generate("judge", [{"role": "user", "content": "x"}])
    assert resp.text == "cloud" and sleeps == [1.0] and not server.requests


async def test_cloud_long_retry_after_falls_back_immediately(settings: Settings, server: FakeOllamaServer) -> None:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    gw = live(settings, server, cloud=make_cloud([429], seen, sleeps, retry_after="3600"), cloud_ok=True)
    resp = await gw.generate("judge", [{"role": "user", "content": "x"}])
    assert len(seen) == 1 and sleeps == [] and resp.usage.provider == "ollama"


async def test_cloud_failure_and_local_failure_surface_local_error(settings: Settings) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    seen: list[httpx.Request] = []
    local = OllamaProvider("http://x", httpx.AsyncClient(transport=httpx.MockTransport(down)))
    gw = Gateway(settings, local=local, cloud=make_cloud([500], seen, []), cloud_ok=True)
    with pytest.raises(ModelTransientError, match="ollama"):
        await gw.generate("judge", [{"role": "user", "content": "x"}])
    assert len(seen) == 1


def test_cloud_key_never_in_repr() -> None:
    provider = OpenAICompatProvider("https://api.groq.test/openai/v1", "gsk_SECRET")
    assert "gsk_SECRET" not in repr(provider)
    assert provider.url.endswith("/openai/v1/chat/completions")
    assert OpenAICompatProvider("https://h", "k").url == "https://h/v1/chat/completions"
    gemini = OpenAICompatProvider("https://generativelanguage.googleapis.com/v1beta/openai", "AIza_test_1",
                                  name="gemini")
    assert gemini.url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert gemini.name == "gemini" and "AIza_test_1" not in repr(gemini)


async def test_cloud_key_not_logged(settings: Settings, server: FakeOllamaServer,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[httpx.Request] = []
    gw = live(settings, server, cloud=make_cloud([429, 401], seen, []), cloud_ok=True)
    await gw.generate("judge", [{"role": "user", "content": "x"}])
    captured = capsys.readouterr()
    assert "gsk_SECRET" not in captured.out + captured.err


def test_default_cloud_built_only_with_url_and_key(tmp_path: Path) -> None:
    base = Settings(llm_mode="live", llm_cache_dir=tmp_path)
    assert Gateway(base)._shared.cloud is None
    configured = base.model_copy(update={"cloud_base_url": "https://h/v1", "cloud_api_key": "k"})
    assert isinstance(Gateway(configured)._shared.cloud, OpenAICompatProvider)
    assert Gateway(configured.model_copy(update={"llm_mode": "replay"}))._shared.cloud is None


def test_local_provider_gets_the_configured_context_window() -> None:
    assert Settings().ollama_num_ctx == 8192  # Ollama's own default (4096) cuts a 3K-token prompt plus its answer
    assert Settings.from_env({"HMAP_OLLAMA_NUM_CTX": "16384"}).ollama_num_ctx == 16384
    gw = Gateway(Settings(llm_mode="live", ollama_num_ctx=12000))
    assert gw._shared.local.num_ctx == 12000  # type: ignore[attr-defined]

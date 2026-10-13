"""Team cloud key pool (doc 02 §2.5, item 1.14b). MockTransport only: no network, fake keys, no Ollama."""

import asyncio
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from hmap.core.config import CLOUD_CHAT_ROLES, DEFAULT_CLOUD_ROLE_MAP, Settings, parse_cloud_role_map
from hmap.core.llm import (
    ChatRequest,
    CloudRouter,
    Gateway,
    KeyPool,
    LLMProviderError,
    OllamaProvider,
    OpenAICompatProvider,
    Role,
    fingerprint,
)
from hmap.core.llm.providers import chat_completions_url

from .conftest import FakeOllamaServer

GROQ_KEYS = ["gsk_test_1", "gsk_test_2", "gsk_test_3"]
GEMINI_KEYS = ["AIza_test_1"]
ALL_KEYS = [*GROQ_KEYS, *GEMINI_KEYS]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
MSG = [{"role": "user", "content": "write SECRET_PROMPT_TEXT"}]

Step = str | int | tuple[int, str]  # "ok" | "conn" | status | (429, retry-after)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeCloud:
    """Answers OpenAI-compatible chat calls. ``script[key]`` is a list of steps consumed in order (last repeats)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.script: dict[str, list[Step]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = request.headers["authorization"].removeprefix("Bearer ")
        steps = self.script.get(key, ["ok"])
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if step == "conn":
            raise httpx.ConnectError("down", request=request)
        if step == "ok":
            body = json.loads(request.content)
            return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 3,
                                                                               "completion_tokens": 2},
                                             "choices": [{"message": {"content": f"cloud:{request.url.host}"}}]})
        if isinstance(step, tuple):
            return httpx.Response(step[0], headers={"retry-after": step[1]}, json={"error": "rate"})
        assert isinstance(step, int)
        if step == 400:  # a provider that echoes the key back in its error body
            return httpx.Response(400, text=f"bad request for key {key}")
        return httpx.Response(step, json={"error": "nope"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    @property
    def keys_used(self) -> list[str]:
        return [r.headers["authorization"].removeprefix("Bearer ") for r in self.requests]

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


@pytest.fixture
def cloud() -> FakeCloud:
    return FakeCloud()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def pool_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={
        "groq_api_keys": Settings(groq_api_keys=GROQ_KEYS).groq_api_keys,
        "gemini_api_keys": Settings(gemini_api_keys=GEMINI_KEYS).gemini_api_keys,
        "cloud_role_map": {"coder": [("groq", "llama-x"), ("gemini", "gemini-x")]}})


def make_gateway(s: Settings, server: FakeOllamaServer, cloud: FakeCloud, clock: FakeClock,
                 **kwargs: Any) -> Gateway:
    router = CloudRouter.from_settings(s, client=cloud.client(), clock=clock)
    return Gateway(s, local=OllamaProvider(s.ollama_base_url, server.client()), cloud_router=router, **kwargs)


def fp(key: str) -> str:
    return fingerprint("gemini" if key.startswith("AIza") else "groq", key)


# ---------------------------------------------------------------------- settings / parsing
def test_cloud_role_map_parsing() -> None:
    assert parse_cloud_role_map("coder=groq:llama-3.3-70b|gemini:gemini-2.5-flash, reasoner=gemini:g") == {
        "coder": [("groq", "llama-3.3-70b"), ("gemini", "gemini-2.5-flash")], "reasoner": [("gemini", "g")]}
    assert parse_cloud_role_map("") == {} and parse_cloud_role_map(" , ") == {}
    assert parse_cloud_role_map("coder=GROQ:qwen/qwen3-32b:free") == {"coder": [("groq", "qwen/qwen3-32b:free")]}
    assert parse_cloud_role_map("judge=cloud:m") == {"judge": [("cloud", "m")]}
    assert parse_cloud_role_map("none") == {} and parse_cloud_role_map(" OFF ") == {}


def test_default_cloud_role_map_covers_every_chat_role_and_keeps_judge_independent() -> None:
    default = parse_cloud_role_map(DEFAULT_CLOUD_ROLE_MAP)
    assert set(default) == set(CLOUD_CHAT_ROLES) and "embed" not in default
    assert default["judge"][0] not in (default["reasoner"][0], default["coder"][0])


@pytest.mark.parametrize(("raw", "match"), [
    ("coder", "expected role=provider:model"),
    ("coder=", "expected role=provider:model"),
    ("wizard=groq:m", "unknown or non-chat role"),
    ("embed=groq:m", "unknown or non-chat role"),
    ("coder=gsk_pasted_secret:m", "unknown provider"),
    ("coder=groq", "expected provider:model"),
    ("coder=groq:m|gemini:", "provider #2: expected provider:model"),
    ("coder=groq:m,coder=gemini:m", "listed twice"),
])
def test_cloud_role_map_invalid_entries_never_echo_values(raw: str, match: str) -> None:
    with pytest.raises(ValueError, match=match) as info:
        parse_cloud_role_map(raw)
    assert "gsk_pasted_secret" not in str(info.value)
    with pytest.raises(ValueError):
        Settings.from_env({"HMAP_CLOUD_ROLE_MAP": raw})


def test_settings_from_env_keys_hidden() -> None:
    s = Settings.from_env({"HMAP_GROQ_API_KEYS": " gsk_test_1, ,gsk_test_2,gsk_test_1,",
                           "HMAP_GEMINI_API_KEYS": "AIza_test_1",
                           "HMAP_CLOUD_ROLE_MAP": "coder=groq:a|gemini:b",
                           "HMAP_GEMINI_BASE_URL": "https://gem.test/v1beta/openai", "HMAP_CLOUD_OK": "false"})
    assert s.cloud_keys("groq") == ["gsk_test_1", "gsk_test_2"]
    assert s.cloud_keys("gemini") == ["AIza_test_1"] and s.cloud_keys("cloud") == []
    assert s.cloud_role_map == {"coder": [("groq", "a"), ("gemini", "b")]}
    assert s.groq_base_url == "https://api.groq.com/openai/v1" and s.cloud_base_url_for("gemini") == (
        "https://gem.test/v1beta/openai")
    assert s.cloud_ok is False and Settings.from_env({}).cloud_ok is True
    for text in (repr(s), str(s), s.model_dump_json(), str(s.model_dump())):
        assert not any(k in text for k in ALL_KEYS)
    defaults = Settings.from_env({})
    assert defaults.groq_api_keys == [] and defaults.cloud_role_map == parse_cloud_role_map(DEFAULT_CLOUD_ROLE_MAP)
    assert Settings.from_env({"HMAP_CLOUD_ROLE_MAP": "none"}).cloud_role_map == {}
    assert defaults.gemini_base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert Settings(groq_api_keys="a, b").cloud_keys("groq") == ["a", "b"]
    assert Settings(cloud_role_map="fast=groq:m").cloud_role_map == {"fast": [("groq", "m")]}


def test_chat_completions_url_building() -> None:
    assert chat_completions_url("https://api.groq.com/openai/v1") == GROQ_URL
    assert chat_completions_url("https://generativelanguage.googleapis.com/v1beta/openai/") == GEMINI_URL
    assert chat_completions_url("https://h/v1beta") == "https://h/v1beta/chat/completions"
    assert chat_completions_url("https://h/api/openai") == "https://h/api/openai/chat/completions"
    assert chat_completions_url("https://h") == "https://h/v1/chat/completions"


# ---------------------------------------------------------------------- KeyPool unit
def test_fingerprint_and_lease_hide_the_key() -> None:
    f = fingerprint("groq", "gsk_test_1")
    assert f.startswith("groq:") and len(f) == len("groq:") + 8 and "gsk_test_1" not in f
    assert f == fingerprint("groq", "gsk_test_1") != fingerprint("groq", "gsk_test_2")
    pool = KeyPool("groq", GROQ_KEYS)
    lease = pool.acquire()
    assert lease is not None and lease.secret() == "gsk_test_1"
    assert "gsk_test" not in repr(lease) + str(lease) + repr(pool) + json.dumps(pool.usage())
    assert len(KeyPool("groq", ["a", " a ", "", "b"])) == 2


def test_pool_default_cooldown_is_exponential_and_capped(clock: FakeClock) -> None:
    pool = KeyPool("groq", ["k"], clock=clock, default_cooldown_s=5, max_default_cooldown_s=12)
    f = pool.fingerprints[0]
    assert [pool.mark_rate_limited(f, None) for _ in range(3)] == [5, 10, 12]
    assert pool.acquire() is None and pool.available() == 0
    clock.now += 12.5
    assert pool.acquire() is not None
    pool.mark_ok(f, input_tokens=1, output_tokens=1)
    assert pool.mark_rate_limited(f, None) == 5  # success resets the strikes
    assert pool.mark_rate_limited(f, 99999999) == 24 * 3600  # absurd retry-after is capped


def test_pool_is_thread_safe() -> None:
    pool = KeyPool("groq", [f"k{i}" for i in range(4)])
    got: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(250):
            lease = pool.acquire()
            assert lease is not None
            pool.mark_ok(lease.fingerprint, input_tokens=1)
            with lock:
                got.append(lease.fingerprint)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    usage = pool.usage()
    assert len(got) == 1000 and sum(u["requests"] for u in usage.values()) == 1000
    assert all(u["requests"] == 250 and u["input_tokens"] == 250 for u in usage.values())


# ---------------------------------------------------------------------- routing through the gateway
async def test_round_robin_across_keys(pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                                       clock: FakeClock) -> None:
    gw = make_gateway(pool_settings, server, cloud, clock)
    for _ in range(4):
        resp = await gw.generate("coder", MSG)
        assert resp.text == "cloud:api.groq.com" and resp.usage.provider == "groq"
    assert cloud.keys_used == ["gsk_test_1", "gsk_test_2", "gsk_test_3", "gsk_test_1"]
    assert set(cloud.urls) == {GROQ_URL}
    assert {json.loads(r.content)["model"] for r in cloud.requests} == {"llama-x"}
    assert not server.requests


async def test_concurrent_calls_spread_over_keys(pool_settings: Settings, server: FakeOllamaServer,
                                                 cloud: FakeCloud, clock: FakeClock) -> None:
    gw = make_gateway(pool_settings, server, cloud, clock)
    await asyncio.gather(*(gw.generate("coder", MSG) for _ in range(9)))
    assert sorted(cloud.keys_used) == sorted(GROQ_KEYS * 3)


async def test_429_cools_only_that_key_and_next_key_used_immediately(
        pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud, clock: FakeClock) -> None:
    cloud.script["gsk_test_1"] = [(429, "30"), "ok"]
    gw = make_gateway(pool_settings, server, cloud, clock)
    started = time.perf_counter()
    resp = await gw.generate("coder", MSG)
    assert time.perf_counter() - started < 1.0  # no sleeping while other keys are free
    assert resp.usage.provider == "groq" and cloud.keys_used == ["gsk_test_1", "gsk_test_2"]
    await gw.generate("coder", MSG)
    await gw.generate("coder", MSG)  # key 1 still cooling: skipped
    assert cloud.keys_used[2:] == ["gsk_test_3", "gsk_test_2"]
    usage = gw.cloud_usage()[fp("gsk_test_1")]
    assert usage["rate_limited"] == 1 and usage["cooling_for_s"] == 30.0
    clock.now += 31
    await gw.generate("coder", MSG)
    await gw.generate("coder", MSG)
    assert "gsk_test_1" in cloud.keys_used[4:]


async def test_429_http_date_retry_after(pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                                         clock: FakeClock) -> None:
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    cloud.script["gsk_test_1"] = [(429, when)]
    gw = make_gateway(pool_settings, server, cloud, clock)
    await gw.generate("coder", MSG)
    assert 110 <= gw.cloud_usage()[fp("gsk_test_1")]["cooling_for_s"] <= 121


async def test_all_keys_cooling_falls_back_to_local(pool_settings: Settings, server: FakeOllamaServer,
                                                    cloud: FakeCloud, clock: FakeClock) -> None:
    for key in ALL_KEYS:
        cloud.script[key] = [(429, "60")]
    gw = make_gateway(pool_settings, server, cloud, clock)
    resp = await gw.generate("coder", MSG)
    assert resp.text == "hello" and resp.usage.provider == "ollama"
    assert cloud.keys_used == ALL_KEYS  # every key tried once, groq first, then gemini
    assert server.paths() == ["/api/chat"] and server.bodies[0]["model"] == "qwen3:8b"
    resp = await gw.generate("coder", MSG)  # everything still cooling: no cloud call at all
    assert resp.usage.provider == "ollama" and len(cloud.requests) == 4 and len(server.requests) == 2
    assert gw.cloud_router is not None and gw.cloud_router.local_fallbacks == 2
    clock.now += 61
    assert (await gw.generate("coder", MSG)).usage.provider == "ollama"
    assert len(cloud.requests) == 8  # cooled down -> retried


async def test_401_disables_key_until_restart(pool_settings: Settings, server: FakeOllamaServer,
                                              cloud: FakeCloud, clock: FakeClock) -> None:
    cloud.script["gsk_test_1"] = [401]
    gw = make_gateway(pool_settings, server, cloud, clock)
    with capture_logs() as logs:
        resp = await gw.generate("coder", MSG)
        assert resp.usage.provider == "groq" and cloud.keys_used == ["gsk_test_1", "gsk_test_2"]
        clock.now += 10_000
        for _ in range(6):
            await gw.generate("coder", MSG)
    assert cloud.keys_used.count("gsk_test_1") == 1
    usage = gw.cloud_usage()[fp("gsk_test_1")]
    assert usage["disabled"] is True and usage["auth_errors"] == 1
    assert [e["event"] for e in logs].count("llm.cloud.key_disabled") == 1


async def test_provider_order_groq_then_gemini(pool_settings: Settings, server: FakeOllamaServer,
                                               cloud: FakeCloud, clock: FakeClock) -> None:
    for key in GROQ_KEYS:
        cloud.script[key] = [403]
    gw = make_gateway(pool_settings, server, cloud, clock)
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "gemini" and resp.text == "cloud:generativelanguage.googleapis.com"
    assert cloud.urls == [GROQ_URL] * 3 + [GEMINI_URL]
    gemini_req = cloud.requests[-1]
    assert gemini_req.headers["authorization"] == "Bearer AIza_test_1"
    assert json.loads(gemini_req.content)["model"] == "gemini-x"


async def test_transient_errors_try_next_key_once_then_move_on(pool_settings: Settings, server: FakeOllamaServer,
                                                              cloud: FakeCloud, clock: FakeClock) -> None:
    cloud.script["gsk_test_1"] = [500]
    cloud.script["gsk_test_2"] = ["conn"]
    gw = make_gateway(pool_settings, server, cloud, clock)
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "gemini"  # groq key 3 not tried: one retry per provider, then next provider
    assert cloud.keys_used == ["gsk_test_1", "gsk_test_2", "AIza_test_1"]
    cloud.script["AIza_test_1"] = [502]
    cloud.script["gsk_test_3"] = [503]
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "ollama"  # transient everywhere -> local
    usage = gw.cloud_usage()
    assert usage[fp("gsk_test_1")]["errors"] == 2 and not usage[fp("gsk_test_1")]["disabled"]


async def test_other_4xx_moves_to_next_provider_and_errors_hide_key(
        pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud, clock: FakeClock) -> None:
    cloud.script["gsk_test_1"] = [400]  # the fake echoes the key in its error body
    gw = make_gateway(pool_settings, server, cloud, clock)
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "gemini" and cloud.keys_used == ["gsk_test_1", "AIza_test_1"]
    provider = OpenAICompatProvider("https://api.groq.com/openai/v1", None, cloud.client(), name="groq")
    with pytest.raises(LLMProviderError) as info:
        await provider.send(ChatRequest(model="m", messages=MSG, role="coder"), api_key="gsk_test_1", model="m")
    assert info.value.details["status"] == 400
    assert "gsk_test_1" not in str(info.value) + repr(info.value.details) + json.dumps(info.value.to_dict())


async def test_cloud_ok_false_never_calls_cloud(pool_settings: Settings, server: FakeOllamaServer,
                                                cloud: FakeCloud, clock: FakeClock) -> None:
    gw = make_gateway(pool_settings, server, cloud, clock)
    local_only = gw.for_plugin("private_project", cloud_ok=False)
    assert (await local_only.generate("coder", MSG)).usage.provider == "ollama"
    assert (await local_only.generate("coder", MSG, allow_cloud=True)).usage.provider == "ollama"
    assert (await gw.generate("coder", MSG, allow_cloud=False)).usage.provider == "ollama"
    off = make_gateway(pool_settings.model_copy(update={"cloud_ok": False}), server, cloud, clock)
    assert (await off.generate("coder", MSG, allow_cloud=True)).usage.provider == "ollama"
    assert not cloud.requests and len(server.requests) == 4
    assert (await gw.for_plugin("demo", cloud_ok=True).generate("coder", MSG)).usage.provider == "groq"


async def test_local_only_copy_blocks_the_pool_and_leaves_the_original(
        pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud, clock: FakeClock) -> None:
    gw = make_gateway(pool_settings, server, cloud, clock).for_plugin("doc_intel")
    private = gw.local_only()                                     # what a local-only project's task gets
    assert private.plugin == "doc_intel" and private.cloud_ok is False
    assert (await private.generate("coder", MSG, allow_cloud=True)).usage.provider == "ollama"
    assert not cloud.requests
    assert (await gw.generate("coder", MSG)).usage.provider == "groq"   # the shared client is unchanged


async def test_unmapped_roles_stay_local(pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                                         clock: FakeClock) -> None:
    gw = make_gateway(pool_settings, server, cloud, clock)
    roles: list[Role] = ["reasoner", "judge", "fast"]
    for role in roles:
        assert (await gw.generate(role, MSG)).usage.provider == "ollama"
    assert (await gw.generate("judge", MSG, allow_cloud=True)).usage.provider == "ollama"
    await gw.embed(["x"])
    assert not cloud.requests


def test_zero_keys_builds_no_cloud(settings: Settings) -> None:
    mapped = settings.model_copy(update={"cloud_role_map": {"coder": [("groq", "m"), ("gemini", "g")]}})
    for s in (settings, mapped):
        assert CloudRouter.from_settings(s) is None
        gw = Gateway(s)
        assert gw.cloud_router is None and gw._shared.cloud is None and gw.cloud_usage() == {}
    keys = settings.model_copy(update={"groq_api_keys": Settings(groq_api_keys="gsk_test_1").groq_api_keys})
    assert CloudRouter.from_settings(keys.model_copy(update={"cloud_role_map": {}})) is None  # HMAP_CLOUD_ROLE_MAP=none
    router = CloudRouter.from_settings(keys.model_copy(update={"cloud_role_map": Settings().cloud_role_map}))
    assert router is not None and set(router.backends) == {"groq"}  # default map; gemini routes dropped (no keys)
    assert all(router.handles(role) for role in ("reasoner", "coder", "judge", "fast", "classify"))


def test_replay_and_fake_modes_build_no_cloud(pool_settings: Settings) -> None:
    for mode in ("replay", "fake"):
        assert Gateway(pool_settings.model_copy(update={"llm_mode": mode})).cloud_router is None
    gw = Gateway(pool_settings)  # live: a real router is built (no request is made)
    assert gw.cloud_router is not None and gw.cloud_router.handles("coder")
    assert sorted(gw.cloud_usage()) == sorted(fp(k) for k in ALL_KEYS)
    assert not any(k in repr(gw.cloud_router) for k in ALL_KEYS)


async def test_only_keyed_providers_are_routed(settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                                               clock: FakeClock) -> None:
    s = settings.model_copy(update={"gemini_api_keys": Settings(gemini_api_keys="AIza_test_1").gemini_api_keys,
                                    "cloud_role_map": {"coder": [("groq", "llama-x"), ("gemini", "gemini-x")]}})
    gw = make_gateway(s, server, cloud, clock)
    assert (await gw.generate("coder", MSG)).usage.provider == "gemini" and cloud.urls == [GEMINI_URL]


async def test_legacy_single_provider_usable_as_cloud_route(settings: Settings, server: FakeOllamaServer,
                                                            cloud: FakeCloud, clock: FakeClock) -> None:
    s = settings.model_copy(update={"cloud_base_url": "https://legacy.test/v1", "cloud_api_key": "legacy_test_key",
                                    "cloud_role_map": {"judge": [("cloud", "big")]}})
    gw = make_gateway(s, server, cloud, clock)
    resp = await gw.generate("judge", MSG)
    assert resp.usage.provider == "cloud" and cloud.urls == ["https://legacy.test/v1/chat/completions"]
    assert list(gw.cloud_usage()) == [fingerprint("cloud", "legacy_test_key")]


async def test_usage_counters(pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                              clock: FakeClock) -> None:
    cloud.script["gsk_test_2"] = [(429, "5"), "ok"]
    cloud.script["gsk_test_3"] = [401]
    gw = make_gateway(pool_settings, server, cloud, clock)
    for _ in range(4):
        await gw.generate("coder", MSG)
    # calls: k1 ok | k2 429 -> k3 401 -> k1 ok | k1 ok (k2 cooling, k3 disabled) | k1 ok
    usage = gw.cloud_usage()
    assert usage[fp("gsk_test_1")] == {"provider": "groq", "requests": 4, "ok": 4, "input_tokens": 12,
                                       "output_tokens": 8, "rate_limited": 0, "auth_errors": 0, "errors": 0,
                                       "disabled": False, "cooling_for_s": 0.0}
    assert usage[fp("gsk_test_2")]["rate_limited"] == 1 and usage[fp("gsk_test_2")]["cooling_for_s"] == 5.0
    assert usage[fp("gsk_test_3")]["disabled"] and usage[fp("gsk_test_3")]["requests"] == 1
    assert usage[fp("AIza_test_1")]["requests"] == 0


# ---------------------------------------------------------------------- secrecy: logs, cache
async def test_no_key_or_content_in_logs(pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                                         clock: FakeClock, capsys: pytest.CaptureFixture[str]) -> None:
    cloud.script.update({"gsk_test_1": [(429, "1"), "ok"], "gsk_test_2": [401], "gsk_test_3": [500],
                         "AIza_test_1": ["ok", 400]})
    gw = make_gateway(pool_settings, server, cloud, clock)
    with capture_logs() as logs:
        await gw.generate("coder", MSG)  # 429, 401, 500 -> gemini ok
        await gw.generate("coder", MSG)  # k1 cooling, k2 disabled, k3 500 -> gemini 400 -> local
    calls = [e for e in logs if e["event"] == "llm.cloud.call"]
    assert {e["outcome"] for e in calls} == {"rate_limited", "auth_error", "error", "ok", "rejected",
                                             "fallback_local"}
    for e in calls:
        assert {"plugin", "role", "provider", "model", "key", "input_tokens", "output_tokens", "latency_s",
                "outcome"} <= set(e)
    ok = next(e for e in calls if e["outcome"] == "ok")
    assert ok["provider"] == "gemini" and ok["model"] == "gemini-x" and ok["key"] == fp("AIza_test_1")
    assert ok["input_tokens"] == 3 and ok["output_tokens"] == 2 and ok["role"] == "coder"
    text = repr(logs) + "".join(capsys.readouterr())
    assert not any(k in text for k in ALL_KEYS)
    assert "SECRET_PROMPT_TEXT" not in text


async def test_record_mode_cache_holds_no_key(pool_settings: Settings, server: FakeOllamaServer,
                                              cloud: FakeCloud, clock: FakeClock) -> None:
    s = pool_settings.model_copy(update={"llm_mode": "record"})
    gw = make_gateway(s, server, cloud, clock).for_plugin("coder_agent")
    resp = await gw.generate("coder", MSG)
    assert resp.usage.provider == "groq"
    files = list(Path(s.llm_cache_dir).rglob("*.json"))
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    record = json.loads(raw)
    assert record["provider"] == "groq" and record["model"] == "llama-x" and "headers" not in record["request"]
    assert not any(k in raw for k in ALL_KEYS) and "Bearer" not in raw
    replay = Gateway(s.model_copy(update={"llm_mode": "replay"})).for_plugin("coder_agent")
    assert (await replay.generate("coder", MSG)).text == resp.text


async def test_gemini_never_gets_a_seed(pool_settings: Settings, server: FakeOllamaServer, cloud: FakeCloud,
                                        clock: FakeClock) -> None:
    """Gemini's OpenAI-compatible API rejects `seed` (400): it must not be sent, or seeded calls skip Gemini."""
    s = pool_settings.model_copy(update={"cloud_role_map": {"reasoner": [("gemini", "gemini-x"), ("groq", "g")]}})
    resp = await make_gateway(s, server, cloud, clock).generate("reasoner", MSG, seed=7)
    assert resp.usage.provider == "gemini"
    sent = json.loads(cloud.requests[0].content)
    assert "seed" not in sent and sent["reasoning_effort"] == "none"  # thinking off unless asked for
    groq_only = s.model_copy(update={"cloud_role_map": {"reasoner": [("groq", "g")]}})
    await make_gateway(groq_only, server, cloud, clock).generate("reasoner", MSG, seed=7)
    groq_sent = json.loads(cloud.requests[-1].content)
    assert groq_sent["seed"] == 7 and "reasoning_effort" not in groq_sent  # model "g" is not gpt-oss
    oss = s.model_copy(update={"cloud_role_map": {"reasoner": [("groq", "openai/gpt-oss-120b")]}})
    await make_gateway(oss, server, cloud, clock).generate("reasoner", MSG)
    assert json.loads(cloud.requests[-1].content)["reasoning_effort"] == "low"
    await make_gateway(s, server, cloud, clock).generate("reasoner", MSG, think=True)
    assert "reasoning_effort" not in json.loads(cloud.requests[-1].content)

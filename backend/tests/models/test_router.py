import pytest

from hmap.agents.models.hardware import Hardware
from hmap.agents.models.model import ModelRow
from hmap.agents.models.router import ModelRouter, load_table
from hmap.agents.models.store import MemoryModelStore
from hmap.core.config import Settings
from hmap.core.contracts.domain import ModelSpec
from hmap.core.llm import CloudRouter, Gateway, OllamaProvider
from hmap.core.plugins import RouteQuery
from tests.core.llm.test_key_pool import GEMINI_KEYS, GROQ_KEYS, MSG, FakeClock, FakeCloud

from .helpers import FakeOllama

ROUTES = (("gemini", "flash"), ("groq", "gpt-oss-120b"))


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def q(role: str = "reasoner", *, plugin: str = "planning", routes: tuple[tuple[str, str], ...] = ROUTES,
      pool: dict[str, int] | None = None, est: int = 1000, cloud: bool = True,
      model: str | None = "qwen3.5:9b") -> RouteQuery:
    return RouteQuery(role=role, plugin=plugin, est_tokens=est, max_tokens=500, structured=True, cloud_allowed=cloud,
                      default_model=model, default_routes=routes,
                      pool=pool if pool is not None else {"gemini": 1, "groq": 3})


def row(model: str, *, status: str = "installed", mem: float = 5.0) -> ModelRow:
    return ModelRow(spec=ModelSpec(id=model, mem_gb=mem, status=status), source="ollama")  # type: ignore[arg-type]


def router(**kw: object) -> ModelRouter:
    s = kw.pop("settings", None) or Settings(router="on")
    return ModelRouter(s, store=MemoryModelStore(), table=kw.pop("table", {}), background=False, **kw)  # type: ignore[arg-type]


def test_off_means_no_opinion() -> None:
    assert router(settings=Settings(router="off")).decide(q()) is None


def test_default_keeps_the_configured_order_and_logs_it() -> None:
    r = router()
    plan = r.decide(q())
    assert plan is not None and plan.cloud_routes is None and plan.local_model is None
    rec = next(iter(r._pending.values()))
    assert rec.chain == ["gemini:flash", "groq:gpt-oss-120b", "ollama:qwen3.5:9b"] and rec.rule == "configured order"
    assert (rec.decision.backend, rec.decision.model) == ("gemini", "flash")


def test_overrides() -> None:
    s = Settings(router="on", route_overrides={"coding:coder": "groq:qwen/qwen3.8-27b", "*:fast": "qwen3.5:4b"})
    r = router(settings=s)
    plan = r.decide(q("coder", plugin="coding"))
    assert plan is not None and plan.cloud_routes == [("groq", "qwen/qwen3.8-27b")]
    plan = r.decide(q("fast", plugin="research"))
    assert plan is not None and plan.cloud_routes == [] and plan.local_model == "qwen3.5:4b"
    assert "override" in plan.reason


def test_a_provider_without_usable_keys_goes_last() -> None:
    plan = router().decide(q(pool={"gemini": 0, "groq": 3}))
    assert plan is not None and plan.cloud_routes == [("groq", "gpt-oss-120b"), ("gemini", "flash")]
    assert "no key usable" in plan.reason


def test_a_route_that_answered_429_goes_last_until_it_succeeds() -> None:
    clock = Clock()
    r = router(clock=clock)
    r.observe_attempt("gemini", "flash", "reasoner", "rate_limited", 0.1)
    plan = r.decide(q())
    assert plan is not None and plan.cloud_routes == [("groq", "gpt-oss-120b"), ("gemini", "flash")]
    r.observe_attempt("gemini", "flash", "reasoner", "ok", 0.1)
    plan = r.decide(q())
    assert plan is not None and plan.cloud_routes is None
    r.observe_attempt("gemini", "flash", "reasoner", "rate_limited", 0.1)
    clock.now += 61                                  # an old 429 no longer counts
    plan = r.decide(q())
    assert plan is not None and plan.cloud_routes is None


def test_per_minute_budget() -> None:
    clock = Clock()
    r = router(clock=clock)
    for _ in range(10):                              # gemini free tier: 10 requests / minute / key, 1 key
        r.observe_attempt("gemini", "flash", "reasoner", "ok", 0.1)
    plan = r.decide(q())
    assert plan is not None and plan.cloud_routes is not None and plan.cloud_routes[0] == ("groq", "gpt-oss-120b")
    assert "budget" in plan.reason


def test_a_route_that_rejected_a_prompt_this_size_is_skipped() -> None:
    r = router()
    r.decide(q(est=9000))
    r.observe_attempt("groq", "gpt-oss-120b", "reasoner", "rejected", 0.1)
    plan = r.decide(q(est=9500))
    assert plan is not None and plan.cloud_routes == [("gemini", "flash")] and "rejected" in plan.reason
    plan = r.decide(q(est=2000))                      # smaller prompts still go there
    assert plan is not None and plan.cloud_routes is None


def test_benchmark_table_reorders_only_on_a_clear_difference() -> None:
    table = {"reasoner": {"gemini:flash": 0.70, "groq:gpt-oss-120b": 0.82}}
    plan = router(table=table).decide(q())
    assert plan is not None and plan.cloud_routes == [("groq", "gpt-oss-120b"), ("gemini", "flash")]
    assert "best measured reasoner quality" in plan.reason
    close = {"reasoner": {"gemini:flash": 0.80, "groq:gpt-oss-120b": 0.82}}
    plan = router(table=close).decide(q())
    assert plan is not None and plan.cloud_routes is None
    partial = {"reasoner": {"groq:gpt-oss-120b": 0.99}}       # not every route measured: keep the order
    plan = router(table=partial).decide(q())
    assert plan is not None and plan.cloud_routes is None


def test_local_only_project_gets_no_cloud() -> None:
    plan = router().decide(q(cloud=False))
    assert plan is not None and plan.cloud_routes == []


def test_local_choice() -> None:
    local = {"qwen3.5:9b": row("qwen3.5:9b", mem=5.8), "qwen3.5:4b": row("qwen3.5:4b", mem=3.4)}
    table = {"reasoner": {"qwen3.5:9b": 0.83, "qwen3.5:4b": 0.82}, "coder": {"qwen3.5:9b": 0.68, "qwen3.5:4b": 0.56}}
    hw = Hardware(total_gb=16.0, resident={"qwen3.5:4b": 3.4})
    r = router(local=local, table=table, hardware=hw)
    plan = r.decide(q("reasoner"))
    assert plan is not None and plan.local_model == "qwen3.5:4b" and "no swap" in plan.reason
    plan = r.decide(q("coder"))                      # 0.56 vs 0.68: worth the swap
    assert plan is not None and plan.local_model is None
    plan = router(local={"qwen3.5:4b": row("qwen3.5:4b")}, table=table).decide(q("coder"))
    assert plan is not None and plan.local_model == "qwen3.5:4b" and "not installed" in plan.reason
    disabled = {"qwen3.5:9b": row("qwen3.5:9b", status="disabled"), "qwen3.5:4b": row("qwen3.5:4b")}
    plan = router(local=disabled, table=table).decide(q("coder"))
    assert plan is not None and plan.local_model == "qwen3.5:4b"
    small = router(local=local, table=table, hardware=Hardware(total_gb=8.0)).decide(q("coder"))
    assert small is not None and small.local_model is None and "no installed local model fits" in small.reason
    unknown = router(local=None).decide(q("coder"))  # Ollama never answered: keep the role map
    assert unknown is not None and unknown.local_model is None


@pytest.fixture
def pool() -> Settings:
    return Settings(router="on", groq_api_keys=GROQ_KEYS, gemini_api_keys=GEMINI_KEYS,
                    role_map={"reasoner": "qwen3.5:9b"},
                    cloud_role_map={"reasoner": [("gemini", "gemini-x"), ("groq", "llama-x")]})


async def test_through_the_gateway(pool: Settings) -> None:
    """The real call path: the router reorders, the gateway follows, the decision is logged with its outcome."""
    cloud, ollama = FakeCloud(), FakeOllama()
    for key in GEMINI_KEYS:
        cloud.script[key] = [(429, "30")]
    store = MemoryModelStore()
    r = ModelRouter(pool, store=store, table={}, background=False)
    gw = Gateway(pool, local=OllamaProvider(pool.ollama_base_url, ollama.client()), mode="live", route=r,
                 cloud_router=CloudRouter.from_settings(pool, client=cloud.client(), clock=FakeClock()))
    first = await gw.for_plugin("planning").generate("reasoner", MSG)
    assert first.usage.provider == "groq"                        # gemini 429 -> next provider (the pool's own rule)
    second = await gw.for_plugin("planning").generate("reasoner", MSG)
    assert second.usage.provider == "groq"
    gemini_calls = [u for u in cloud.urls if "googleapis" in u]
    assert len(gemini_calls) == 1                                # the router skipped the cooling route the 2nd time
    await r.flush()
    recs = await store.recent_routes()
    assert len(recs) == 2 and all(x.ok for x in recs)
    newest, oldest = recs
    assert oldest.attempts == 2 and oldest.rate_limited == 1 and oldest.answered_by == "groq:llama-x"
    assert newest.attempts == 1 and newest.rule == "rules" and newest.chain[0] == "groq:llama-x"


async def test_router_off_through_the_gateway_is_todays_behaviour(pool: Settings) -> None:
    cloud, ollama = FakeCloud(), FakeOllama()
    for key in GEMINI_KEYS:
        cloud.script[key] = [(429, "30")]
    off = pool.model_copy(update={"router": "off"})
    r = ModelRouter(off, store=MemoryModelStore(), table={}, background=False)
    gw = Gateway(off, local=OllamaProvider(off.ollama_base_url, ollama.client()), mode="live", route=r,
                 cloud_router=CloudRouter.from_settings(off, client=cloud.client(), clock=FakeClock()))
    for _ in range(2):
        await gw.generate("reasoner", MSG)
    assert r.decisions == 0


def test_load_table_missing_file(tmp_path: object) -> None:
    from pathlib import Path

    assert load_table(Path(str(tmp_path)) / "none.json") == {}


async def test_configure_builds_scheduler_and_servers() -> None:
    r = ModelRouter(background=False)
    r.configure(Settings(router="on", mlx_base_url="http://mlx/v1"))
    assert r.scheduler is not None and set(r.servers) == {"mlx"}
    r.local = {"mlx:adapter": row("mlx:adapter")}
    plan = r.decide(q(model="mlx:adapter", cloud=False))
    assert plan is not None and plan.local is r.servers["mlx"]
    off = ModelRouter(background=False)
    off.configure(Settings(router="off"))
    assert off.scheduler is None
    await r.aclose()

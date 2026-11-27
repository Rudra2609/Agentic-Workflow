import asyncio

from hmap.agents.models.hardware import Hardware, snapshot_specs
from hmap.agents.models.scheduler import Scheduler
from hmap.core.llm.errors import LLMProviderError
from hmap.core.llm.providers.base import ChatRequest

from .helpers import MemoryBackend

SIZES = {"qwen3.5:9b": 5.9, "qwen3.5:4b": 2.9, "qwen3:8b": 6.4, "nomic-embed-text:latest": 0.3}


def req(model: str, role: str = "reasoner") -> ChatRequest:
    return ChatRequest(model=model, messages=[{"role": "user", "content": "x"}], role=role)


def scheduler(backend: MemoryBackend, hw: Hardware | None, **kw: object) -> Scheduler:
    specs = snapshot_specs()
    return Scheduler(backend, specs=lambda m: specs.get(m), hardware=lambda: hw, **kw)  # type: ignore[arg-type]


async def test_no_oom_under_mixed_load() -> None:
    """Item 11.4: 4b + 9b + 8b + embeddings at once on a 16 GB machine never overflow the model budget."""
    backend = MemoryBackend(capacity_gb=7.5, sizes=SIZES)
    hw = Hardware(total_gb=16.0)
    s = scheduler(backend, hw)

    async def call(model: str, role: str) -> None:
        await s.submit(req(model, role))
        hw.resident = dict(backend.loaded)

    jobs = [call(m, r) for _ in range(5) for m, r in (("qwen3.5:9b", "reasoner"), ("qwen3.5:4b", "fast"),
                                                       ("qwen3:8b", "coder"), ("nomic-embed-text:latest", "fast"))]
    await asyncio.gather(*jobs)
    assert backend.oom == 0 and backend.peak <= 7.5
    assert s.stats.calls == 20 and s.stats.unloads >= 1


async def test_without_the_scheduler_the_same_load_overflows() -> None:
    backend = MemoryBackend(capacity_gb=7.5, sizes=SIZES)
    results = await asyncio.gather(*[backend.chat(req(m)) for m in ("qwen3.5:9b", "qwen3.5:4b", "qwen3:8b")],
                                   return_exceptions=True)
    assert backend.oom >= 1 and any(isinstance(r, LLMProviderError) for r in results)


async def test_priority_then_swap_grouping() -> None:
    backend = MemoryBackend(capacity_gb=100, sizes=SIZES)
    s = scheduler(backend, Hardware(total_gb=64.0))
    s.loaded = "qwen3.5:9b"
    s._running = 1                     # hold the queue while it fills
    futs = [asyncio.ensure_future(s.submit(req(m, r))) for m, r in
            (("qwen3.5:4b", "coder"), ("qwen3.5:9b", "coder"), ("qwen3.5:4b", "reasoner"), ("qwen3.5:9b", "reasoner"),
             ("qwen3.5:4b", "fast"))]
    await asyncio.sleep(0)
    s._running = 0
    s._pump()
    await asyncio.gather(*futs)
    # fast first (it loads the 4b); then the reasoners, the 4b one first (already loaded: no swap); then the
    # coders, the 9b one first (loaded by then)
    assert backend.order == ["fast:qwen3.5:4b", "reasoner:qwen3.5:4b", "reasoner:qwen3.5:9b", "coder:qwen3.5:9b",
                             "coder:qwen3.5:4b"]
    assert s.stats.switches == 3


async def test_starved_call_goes_next() -> None:
    backend = MemoryBackend(capacity_gb=100, sizes=SIZES)
    s = scheduler(backend, None, max_wait_s=0.0)
    s._running = 1
    old = asyncio.ensure_future(s.submit(req("qwen3.5:9b", "coder")))
    await asyncio.sleep(0.01)
    new = asyncio.ensure_future(s.submit(req("qwen3.5:4b", "fast")))
    await asyncio.sleep(0)
    s._running = 0
    s._pump()
    await asyncio.gather(old, new)
    assert backend.order[0] == "coder:qwen3.5:9b"


async def test_a_model_that_does_not_fit_is_refused() -> None:
    backend = MemoryBackend(capacity_gb=3.0, sizes=SIZES)
    s = scheduler(backend, Hardware(total_gb=8.0))
    try:
        await s.submit(req("qwen3.5:9b"))
    except LLMProviderError as exc:
        assert "does not fit" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a refusal")
    assert s.stats.refused == 1 and backend.loaded == {}
    assert (await s.submit(req("nomic-embed-text:latest", "fast"))).text == "ok"   # embedders are always admitted


async def test_unknown_machine_state_admits() -> None:
    backend = MemoryBackend(capacity_gb=100, sizes=SIZES)
    s = scheduler(backend, None)
    assert (await s.provider().chat(req("qwen3.5:9b"))).text == "ok" and s.loaded == "qwen3.5:9b"

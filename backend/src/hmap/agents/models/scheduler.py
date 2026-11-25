"""Request scheduler for the local models (item 11.4). Cloud calls never come here (the key pool has its own
rotation and cooldowns).

On a 16 GB laptop one heavy model fits next to the demo stack, and a switch costs a cold load (4-10 s measured). So:
- **priority by role**: interactive ``fast`` / ``classify`` first, then ``reasoner`` / ``judge`` / ``vision``, then
  ``coder`` (batch);
- **swap-aware**: among the waiting calls of the best priority, the ones for the model already loaded go first, so
  queued calls are grouped by model before switching; a call waiting longer than ``max_wait_s`` goes next whatever
  model it needs (no starvation);
- **concurrency by RAM**: ``slots`` heavy calls at once (1 on 16 GB: Ollama serialises one model anyway);
- **admission**: before a call runs, its model must fit (:func:`hardware.feasible`). ``fits_alone`` → the other
  heavy models are unloaded first (the Sprint-1 guard: the embedder + one heavy model resident,
  ``OLLAMA_MAX_LOADED_MODELS=2``); ``does_not_fit`` → refused with a clear error, never loaded into an out-of-memory
  crash. A model whose size is unknown is admitted (the memory model cannot say no).
"""

import asyncio
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from hmap.agents.models.hardware import Hardware, feasible
from hmap.agents.models.model import ROLE_PRIORITY
from hmap.core.llm.base import LLMResponse
from hmap.core.llm.errors import LLMProviderError
from hmap.core.llm.providers.base import ChatRequest
from hmap.core.tracing import get_logger

log = get_logger("hmap.models.scheduler")


class LocalBackend(Protocol):
    name: str

    async def chat(self, request: ChatRequest) -> LLMResponse: ...

    async def unload(self, model: str) -> None: ...


def is_embedder(model: str) -> bool:
    return "embed" in model


@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    model: str = field(compare=False)
    request: ChatRequest = field(compare=False)
    future: "asyncio.Future[LLMResponse]" = field(compare=False)
    enqueued: float = field(compare=False, default_factory=time.monotonic)


@dataclass
class SchedulerStats:
    calls: int = 0
    switches: int = 0
    unloads: int = 0
    refused: int = 0
    max_queue: int = 0
    waited_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Scheduler:
    def __init__(self, backend: LocalBackend, *, specs: Callable[[str], dict[str, Any] | None],
                 hardware: Callable[[], Hardware | None], slots: int = 1, max_wait_s: float = 30.0,
                 ctx: int = 8192) -> None:
        self.backend = backend
        self.specs = specs
        self.hardware = hardware
        self.slots = max(1, slots)
        self.max_wait_s = max_wait_s
        self.ctx = ctx
        self.loaded: str | None = None           # the heavy model this scheduler last ran
        self.stats = SchedulerStats()
        self._jobs: list[_Job] = []
        self._running = 0
        self._seq = itertools.count()
        self._lock = asyncio.Lock()               # serialises the switch (unload + admission) step

    @property
    def queued(self) -> int:
        return len(self._jobs)

    def provider(self) -> "ScheduledProvider":
        return ScheduledProvider(self)

    async def submit(self, request: ChatRequest) -> LLMResponse:
        future: asyncio.Future[LLMResponse] = asyncio.get_running_loop().create_future()
        self._jobs.append(_Job(ROLE_PRIORITY.get(request.role, 1), next(self._seq), request.model, request, future))
        self.stats.max_queue = max(self.stats.max_queue, len(self._jobs))
        self._pump()
        return await future

    def _pick(self) -> _Job:
        now = time.monotonic()
        starved = [j for j in self._jobs if now - j.enqueued > self.max_wait_s]
        if starved:
            job = min(starved, key=lambda j: j.seq)
        else:
            best = min(j.priority for j in self._jobs)
            top = [j for j in self._jobs if j.priority == best]
            same = [j for j in top if j.model == self.loaded or is_embedder(j.model)]
            job = min(same or top)
        self._jobs.remove(job)
        return job

    def _pump(self) -> None:
        while self._running < self.slots and self._jobs:
            job = self._pick()
            self._running += 1
            asyncio.get_running_loop().create_task(self._run(job))

    async def _admit(self, model: str) -> None:
        if is_embedder(model) or model == self.loaded:
            return
        async with self._lock:
            hw = self.hardware()
            if hw is None:                               # machine state not known yet: nothing to decide on
                self.loaded = model
                return
            fit = feasible(model, self.specs(model), hw, ctx=self.ctx)
            if fit.fit == "does_not_fit":
                self.stats.refused += 1
                raise LLMProviderError(f"{model} does not fit on this machine: {fit.why}",
                                       details={"model": model, "need_gb": fit.need_gb})
            heavy = [m for m in hw.resident if not is_embedder(m) and m != model]
            if self.loaded and self.loaded != model and self.loaded not in heavy:
                heavy.append(self.loaded)
            if heavy and fit.fit in ("fits_alone", "unknown"):
                for other in heavy:                      # the unload guard: one heavy model resident
                    try:
                        await self.backend.unload(other)
                        self.stats.unloads += 1
                    except Exception as exc:  # unloading is best effort; the model may already be gone
                        log.info("models.scheduler.unload_failed", model=other, error=type(exc).__name__)
            if self.loaded is not None:
                self.stats.switches += 1
            self.loaded = model

    async def _run(self, job: _Job) -> None:
        try:
            self.stats.waited_s += time.monotonic() - job.enqueued
            await self._admit(job.model)
            resp = await self.backend.chat(job.request)
            self.stats.calls += 1
            if not job.future.done():
                job.future.set_result(resp)
        except BaseException as exc:  # handed to the waiting caller
            if not job.future.done():
                job.future.set_exception(exc)
        finally:
            self._running -= 1
            self._pump()


class ScheduledProvider:
    """A ``ChatProvider`` that queues through the scheduler (given to the gateway as ``RoutePlan.local``)."""

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler
        self.name = scheduler.backend.name

    async def chat(self, request: ChatRequest) -> LLMResponse:
        return await self.scheduler.submit(request)

"""The refinement hook in the agent runtime (Sprint 4, plan D1, requested by Member 4): ``Plugin.refiners`` adapters
run on a successful result only when the task has ``refine=true``, with the adapter plug-in's model binding; an
adapter failure reports the original result; cancellation still cancels."""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar

import pytest

from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.errors import Cancelled
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.host import resolve_refiners
from hmap.core.runtime.worker import AgentWorker, Refiner
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from tests.core.runtime.fakes import DictInbox, FakeBus, assign_envelope


class BoundLLM:
    """Records which plug-in it was bound to (like ``Gateway.for_plugin``)."""

    def __init__(self, plugin: str = "base") -> None:
        self.plugin = plugin

    def for_plugin(self, name: str) -> "BoundLLM":
        return BoundLLM(name)

    async def generate(self, *a: Any, **k: Any) -> Any: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: return []
    async def classify(self, *a: Any) -> list[Any]: return []


class Writer(BaseAgent):
    name = "writer"
    capabilities: ClassVar[tuple[str, ...]] = ("doc.write",)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        ref = await ctx.put_json({"v": 1}, artifact_type="doc")
        if task.inputs.get("fail"):
            return ctx.result([ref], summary="could not", outcome="failure")
        return ctx.result([ref], summary="written")


class Adapter:
    def __init__(self, behaviour: str = "improve") -> None:
        self.behaviour = behaviour
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, task: TaskAssign, result: TaskResult, ctx: AgentContext) -> TaskResult:
        self.calls.append((task.task_id, getattr(ctx.llm, "plugin", "?")))
        if self.behaviour == "boom":
            raise RuntimeError("adapter broke")
        if self.behaviour == "cancel":
            raise Cancelled("stopped while refining")
        if self.behaviour == "wrong":
            return "not a result"  # type: ignore[return-value]
        await ctx.progress(95, "checking", [result.artifact_refs[0]])
        return result.model_copy(update={"summary": "written; refined"})


@pytest.fixture
async def worker_for() -> AsyncIterator[Callable[..., tuple[AgentWorker, FakeBus]]]:
    made: list[AgentWorker] = []

    def factory(adapter: Adapter) -> tuple[AgentWorker, FakeBus]:
        bus = FakeBus()
        w = AgentWorker(Writer(), bus, BoundLLM(), InMemoryArtifactStore(), InMemoryContextStore(), DictInbox(),
                        agent_id="writer-1", plugin="writers", heartbeat_s=60.0,
                        refiners={"doc.write": Refiner(plugin="refine", adapter=adapter),
                                  "other.cap": Refiner(plugin="refine", adapter=adapter)})
        made.append(w)
        return w, bus

    yield factory
    for w in made:
        await w.stop("teardown", timeout_s=0.5)


def _result(bus: FakeBus) -> dict[str, Any]:
    return bus.of_type("task.result")[-1].payload


async def test_adapter_runs_only_with_the_refine_flag(worker_for) -> None:
    adapter = Adapter()
    worker, bus = worker_for(adapter)
    assert set(worker.refiners) == {"doc.write"}                       # only capabilities this worker serves
    await worker.start()
    await bus.deliver("doc.write", assign_envelope("doc.write"))
    assert adapter.calls == [] and _result(bus)["summary"] == "written"
    env = assign_envelope("doc.write", refine=True)
    await bus.deliver("doc.write", env)
    assert adapter.calls == [(env.task_id, "refine")]                  # the adapter plug-in's model binding
    assert _result(bus)["summary"] == "written; refined"
    progress = [e for e in bus.of_type("task.progress") if e.execution_id == env.execution_id]
    assert progress and progress[-1].payload["artifact_refs"]          # refs travel with progress (plan D5)


async def test_failed_results_are_not_refined(worker_for) -> None:
    adapter = Adapter()
    worker, bus = worker_for(adapter)
    await worker.start()
    await bus.deliver("doc.write", assign_envelope("doc.write", refine=True, inputs={"fail": True}))
    assert adapter.calls == [] and _result(bus)["outcome"] == "failure"


@pytest.mark.parametrize("behaviour", ["boom", "wrong"])
async def test_adapter_failure_reports_the_original_result(worker_for, behaviour: str) -> None:
    worker, bus = worker_for(Adapter(behaviour))
    await worker.start()
    await bus.deliver("doc.write", assign_envelope("doc.write", refine=True))
    assert _result(bus)["summary"] == "written" and _result(bus)["outcome"] == "success"


async def test_cancellation_during_refinement_is_a_cancelled_execution(worker_for) -> None:
    worker, bus = worker_for(Adapter("cancel"))
    await worker.start()
    await bus.deliver("doc.write", assign_envelope("doc.write", refine=True))
    [err] = bus.of_type("error")
    assert err.payload["error_code"] == "CANCELLED" and not bus.of_type("task.result")


def test_host_picks_the_highest_priority_adapter() -> None:
    low, high = Adapter(), Adapter()
    resolved = resolve_refiners([Plugin(name="a", refiners={"x.y": low}, priority=10),
                                 Plugin(name="b", refiners={"x.y": high, "z.w": low}, priority=100)])
    assert resolved["x.y"].adapter is high and resolved["x.y"].plugin == "b" and resolved["z.w"].plugin == "b"
    assert resolve_refiners([]) == {}


async def test_refine_plugin_registers_adapters_for_member_2_and_3() -> None:
    from hmap.agents.refine.plugin import PLUGIN

    assert set(PLUGIN.refiners) == {"document.extract", "plan.generate"}
    await asyncio.sleep(0)

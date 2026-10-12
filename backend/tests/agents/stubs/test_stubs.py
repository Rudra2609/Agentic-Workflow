"""Every stub returns a contract-valid artifact carrying the real task's ids, reports progress, honours cancel."""

import asyncio
import json

import pytest

from hmap.agents.stubs.agents import CAPABILITY_STUBS, EchoAgent, StubAgent
from hmap.agents.stubs.plugin import PLUGIN
from hmap.core.contracts import (
    DOMAIN_MODELS,
    STUBBED_CAPABILITIES,
    ArtifactRef,
    ReviewReport,
    TaskAssign,
    TestReport,
)
from hmap.core.errors import Cancelled
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.discovery import validate_plugin
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore

PROJECT = "P-STUBTEST"


class _NoLLM:
    async def generate(self, *a: object, **k: object) -> object:
        raise AssertionError("stubs must not call the LLM")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError

    async def classify(self, *a: object, **k: object) -> list[object]:
        raise AssertionError


def _ctx(capability: str, **inputs: object) -> tuple[AgentContext, list[tuple[int, str]]]:
    progress: list[tuple[int, str]] = []

    async def record(percent: int, summary: str) -> None:
        progress.append((percent, summary))

    task = TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability=capability,
                      objective="stub run", acceptance_criteria=[], context_refs=[], project_id=PROJECT,
                      inputs=dict(inputs))
    ctx = AgentContext(task=task, agent_id="stub-1", llm=_NoLLM(), artifacts=InMemoryArtifactStore(),
                       context=InMemoryContextStore(), logger=None, _progress=record)
    return ctx, progress


def test_plugin_declares_every_stubbed_capability() -> None:
    validate_plugin(PLUGIN)
    assert PLUGIN.name == "stubs" and PLUGIN.priority == 0
    caps = [c for a in PLUGIN.agents for c in a.capabilities]
    assert sorted(caps) == sorted([*STUBBED_CAPABILITIES, "echo"])
    assert all(a.is_stub for a in PLUGIN.agents)


@pytest.mark.parametrize("agent_cls", CAPABILITY_STUBS, ids=lambda c: c.capabilities[0])
async def test_stub_returns_contract_valid_artifact(agent_cls: type[StubAgent]) -> None:
    capability = agent_cls.capabilities[0]
    ctx, progress = _ctx(capability)
    result = await agent_cls().handle(ctx.task, ctx)
    assert result.outcome == "success" and result.execution_id == ctx.task.execution_id
    ref = ArtifactRef.model_validate(result.artifact_refs[0])
    assert ref.media_type == "application/json" and ref.access_scope == PROJECT
    obj = await ctx.get_json(ref, DOMAIN_MODELS[agent_cls.example])
    data = json.loads(obj.model_dump_json())
    if "project_id" in data:
        assert data["project_id"] == PROJECT
    if "task_id" in data:
        assert data["task_id"] == ctx.task.task_id
    if isinstance(obj, TestReport):
        assert obj.passed and not obj.failures and all(s.status == "passed" for s in obj.stages.values())
    if isinstance(obj, ReviewReport):
        assert obj.recommendation == "PASS"
    assert progress[0][0] == 10 and progress[-1][0] == 100


async def test_echo() -> None:
    ctx, _ = _ctx("echo", k=1)
    result = await EchoAgent().handle(ctx.task, ctx)
    data = json.loads(await ctx.artifacts.get(ArtifactRef.model_validate(result.artifact_refs[0]),
                                              project_id=PROJECT))
    assert data == {"echo": "stub run", "inputs": {"k": 1}}


@pytest.mark.parametrize("agent_cls", [EchoAgent, CAPABILITY_STUBS[0]])
async def test_stub_honours_cancellation(agent_cls: type[BaseAgent]) -> None:
    ctx, _ = _ctx(agent_cls.capabilities[0], stub_delay_s=5)
    run = asyncio.create_task(agent_cls().handle(ctx.task, ctx))
    await asyncio.sleep(0.06)
    ctx.cancelled.set()
    with pytest.raises(Cancelled):
        await asyncio.wait_for(run, timeout=1.0)
    assert await ctx.artifacts.list(PROJECT) == []

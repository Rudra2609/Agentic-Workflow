"""Plug-in conformance: runs automatically for EVERY plug-in under hmap/agents (stubs today, members' agents later).

A member's plug-in that breaks the shared rules fails here with the plug-in named — so the integrator can see which
member's handoff introduced the problem without reading their code.
"""

import json
import re

import pytest
from fastapi import APIRouter

from hmap.core.contracts import TaskAssign
from hmap.core.contracts.capabilities import CAPABILITY_OUTPUTS, STUBBED_CAPABILITIES, CapabilityName
from hmap.core.contracts.common import ContextRef
from hmap.core.contracts.domain import DOMAIN_MODELS
from hmap.core.llm import FakeLLM
from hmap.core.plugins import STRATEGY_SLOTS, Hook, Plugin
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.discovery import capability_table, discover_all, resolve_capabilities
from hmap.core.tracing import get_logger
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore

RESULT = discover_all(None)
PLUGINS = RESULT.plugins
CORE_PREFIXES = ("/projects", "/tasks", "/agents", "/events", "/dead-letters", "/health", "/ws")
EVENT_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
CAP_RE = re.compile(CapabilityName.__metadata__[0].pattern)  # type: ignore[attr-defined]


def test_every_plugin_loads() -> None:
    assert not RESULT.errors, "plug-in load errors:\n" + "\n".join(map(str, RESULT.errors))


@pytest.mark.parametrize("plugin", PLUGINS, ids=lambda p: p.name)
def test_plugin_shape(plugin: Plugin) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_]*", plugin.name), f"{plugin.name}: plug-in names are snake_case"
    assert set(plugin.provides) <= set(STRATEGY_SLOTS)
    names = [a.name for a in plugin.agents]
    assert len(names) == len(set(names)), f"{plugin.name}: duplicate agent names {names}"
    for agent in plugin.agents:
        assert issubclass(agent, BaseAgent), f"{plugin.name}: {agent} must subclass BaseAgent"
        assert agent.name, f"{plugin.name}: {agent.__name__} has no name"
        assert agent.capabilities, f"{plugin.name}: {agent.name} declares no capabilities"
        for cap in agent.capabilities:
            assert CAP_RE.match(cap), f"{plugin.name}: bad capability name {cap!r}"
        assert agent.max_slots >= 1
        assert agent.handle is not BaseAgent.handle, f"{plugin.name}: {agent.name} does not implement handle()"
    for h in plugin.manager_hooks:
        assert isinstance(h, Hook), f"{plugin.name}: manager_hooks must be @hook(...) functions"
        assert EVENT_RE.match(h.event_type), f"{plugin.name}: bad hook event type {h.event_type!r}"
    if plugin.router is not None:
        assert isinstance(plugin.router, APIRouter), f"{plugin.name}: router must be a FastAPI APIRouter"
        for route in plugin.router.routes:
            path = getattr(route, "path", "")
            assert not path.startswith(CORE_PREFIXES), f"{plugin.name}: route {path} shadows a core API path"


def test_no_capability_conflicts_and_nothing_missing() -> None:
    resolve_capabilities(PLUGINS)  # raises CapabilityConflict on equal-priority clashes
    table = {r.capability: r for r in capability_table(PLUGINS, expected=STUBBED_CAPABILITIES)}
    missing = [c for c in STUBBED_CAPABILITIES if table[c].status == "missing"]
    assert not missing, f"no plug-in serves {missing}"


def _ctx(task: TaskAssign, artifacts: InMemoryArtifactStore) -> AgentContext:
    return AgentContext(task=task, agent_id="conformance", llm=FakeLLM(), artifacts=artifacts,
                        context=InMemoryContextStore(), logger=get_logger("conformance"))


STUB_CAPS = [c for c, (_, agent) in resolve_capabilities(PLUGINS).items()
             if c in CAPABILITY_OUTPUTS and agent.is_stub]


@pytest.mark.parametrize("capability", STUB_CAPS)
async def test_stub_outputs_match_their_contract(capability: str) -> None:
    """Every capability currently served by a stub returns an artifact of the contracted type and schema.
    (Members' real agents are checked the same way in their own tests and in the replay-mode e2e run.)"""
    _, agent_cls = resolve_capabilities(PLUGINS)[capability]
    artifacts = InMemoryArtifactStore()
    task = TaskAssign(task_id="T-CONF", execution_id="E-CONF", capability=capability, objective="conformance",
                      acceptance_criteria=[], context_refs=[ContextRef(context_id="CTX-1", version=1)],
                      project_id="P-CONF")
    result = await agent_cls().handle(task, _ctx(task, artifacts))
    artifact_type, contract = CAPABILITY_OUTPUTS[capability]
    assert result.outcome == "success" and result.artifact_refs
    ref = next((r for r in result.artifact_refs if r.artifact_type == artifact_type), None)
    assert ref is not None, f"{capability}: no artifact of type {artifact_type!r} in {result.artifact_refs}"
    data = json.loads(await artifacts.get(ref, project_id="P-CONF"))
    DOMAIN_MODELS[contract].model_validate(data)

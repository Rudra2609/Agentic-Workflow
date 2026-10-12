"""Dev agent host: CLI parsing, the capability table, and running the stubs against an injected FakeBus.
The lazy factories for the real bus / LLM / inbox are deliberately not exercised here."""

import asyncio
import json
from pathlib import Path

import pytest

from hmap.core.config import Settings
from hmap.core.contracts import STUBBED_CAPABILITIES
from hmap.core.errors import HmapError
from hmap.core.runtime import host
from hmap.core.runtime.host import HostDeps, build_parser, cmd_list, format_table, run_agents
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from tests.core.runtime.fakes import DictInbox, FakeBus, FakeLLM, assign_envelope


def test_parser() -> None:
    p = build_parser()
    assert p.parse_args(["run", "--all"]).all is True
    assert p.parse_args(["run", "--only", "research"]).only == "research"
    assert p.parse_args(["list", "--json"]).json is True
    for bad in (["run"], ["run", "--all", "--only", "x"], []):
        with pytest.raises(SystemExit):
            p.parse_args(bad)


def test_list_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = cmd_list(Settings(plugins="stubs"), as_json=True)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["errors"] == []
    rows = {r["capability"]: r for r in out["capabilities"]}
    assert set(rows) == {*STUBBED_CAPABILITIES, "echo"}
    assert all(r["status"] == "stub" and r["plugin"] == "stubs" for r in rows.values())


def test_list_table_and_main(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAP_PLUGINS", "stubs")
    monkeypatch.setattr(host, "configure_logging", lambda *a, **k: None)
    assert host.main(["list"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].split()[:2] == ["CAPABILITY", "STATUS"]
    assert "document.extract" in out and "stub-review-final" in out


def test_list_reports_unknown_plugin(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_list(Settings(plugins="stubs,ghost")) == 1
    assert "ghost" in capsys.readouterr().err


def test_format_table() -> None:
    text = format_table([{"capability": "a", "status": "stub", "plugin": "p", "agent": "x", "priority": 0,
                          "shadowed": ["q", "r"]}])
    assert text.splitlines()[1].split() == ["a", "stub", "p", "x", "0", "q,", "r"]


def test_default_store_factories(tmp_path: Path) -> None:
    settings = Settings(artifact_root=tmp_path)
    store = host.make_artifacts(settings)
    assert isinstance(store, LocalFSArtifactStore) and store.root == tmp_path
    assert isinstance(host.make_contexts(settings), InMemoryContextStore)


async def test_run_stubs_in_one_process() -> None:
    bus = FakeBus()
    deps = HostDeps(bus=bus, llm=FakeLLM(), artifacts=InMemoryArtifactStore(), contexts=InMemoryContextStore(),
                    inbox=DictInbox(), owns_bus=False)
    stop = asyncio.Event()
    running = asyncio.create_task(run_agents(Settings(plugins="stubs"), deps=deps, stop_event=stop))
    await bus.wait_for(lambda b: len(b.of_type("agent.register")) == len(STUBBED_CAPABILITIES) + 1)
    regs = [e.payload for e in bus.of_type("agent.register")]
    assert all(r["is_stub"] and r["plugin"] == "stubs" for r in regs)
    assert {c["name"] for r in regs for c in r["capabilities"]} == {*STUBBED_CAPABILITIES, "echo"}
    env = assign_envelope("echo")
    delivery = await bus.deliver("echo", env)
    assert delivery.settled == "ack" and bus.replies[-1].message_type == "task.result"
    stop.set()
    hosted = await running
    assert len(bus.of_type("agent.deregister")) == len(regs)
    assert all(w.state.value == "OFFLINE" for w in hosted.workers)
    assert not bus.handlers


async def test_run_only_unknown_plugin_fails() -> None:
    deps = HostDeps(bus=FakeBus(), llm=FakeLLM(), artifacts=InMemoryArtifactStore(),
                    contexts=InMemoryContextStore(), inbox=DictInbox(), owns_bus=False)
    with pytest.raises(HmapError, match="no plug-ins"):
        await run_agents(Settings(), only="ghost", deps=deps, stop_event=asyncio.Event())


def test_llm_bound_per_plugin() -> None:
    class Bindable(FakeLLM):
        def __init__(self, plugin: str = "default") -> None:
            self.plugin = plugin

        def for_plugin(self, name: str) -> "Bindable":
            return Bindable(name)

    assert host.llm_for_plugin(Bindable(), "stubs").plugin == "stubs"  # type: ignore[attr-defined]
    plain = FakeLLM()
    assert host.llm_for_plugin(plain, "stubs") is plain

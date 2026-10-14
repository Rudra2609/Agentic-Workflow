"""Plug-in discovery against the real stubs plus a throw-away plug-in package created under tmp_path."""

import textwrap
import uuid
from pathlib import Path

import pytest

from hmap.core.contracts import STUBBED_CAPABILITIES
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import BaseAgent
from hmap.core.runtime.discovery import (
    CapabilityConflict,
    PluginError,
    agents_to_run,
    capability_table,
    discover,
    discover_all,
    resolve_capabilities,
    validate_plugin,
)

REAL_PLUGIN = '''
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import BaseAgent


class FakeExtractor(BaseAgent):
    name = "fake-extractor"
    capabilities = ("document.extract", "document.summarise")


# priority 200: above the stubs (0) and above any member's real plug-in (100), so this test keeps working as the
# real agents arrive sprint by sprint
PLUGIN = Plugin(name="{name}", agents=[FakeExtractor], priority=200)
'''


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


@pytest.fixture
def fake_pkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A package ``<pkg>`` with: a real plug-in, a broken one, one without PLUGIN, a helper without plugin.py."""
    pkg = f"hmap_fake_agents_{uuid.uuid4().hex[:8]}"
    _write(tmp_path, f"{pkg}/__init__.py")
    _write(tmp_path, f"{pkg}/fake_extract/__init__.py")
    _write(tmp_path, f"{pkg}/fake_extract/plugin.py", REAL_PLUGIN.format(name="fake_extract"))
    _write(tmp_path, f"{pkg}/broken/__init__.py")
    _write(tmp_path, f"{pkg}/broken/plugin.py", "import does_not_exist_anywhere\n")
    _write(tmp_path, f"{pkg}/no_plugin_attr/__init__.py")
    _write(tmp_path, f"{pkg}/no_plugin_attr/plugin.py", "X = 1\n")
    _write(tmp_path, f"{pkg}/shared_helpers/__init__.py")
    _write(tmp_path, f"{pkg}/shared_helpers/util.py", "Y = 2\n")
    _write(tmp_path, f"{pkg}/not_a_package.py", "Z = 3\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    return pkg


def test_stubs_are_discovered() -> None:
    plugins = discover()
    stubs = next(p for p in plugins if p.name == "stubs")
    assert stubs.priority == 0
    resolved = resolve_capabilities([stubs])
    assert set(resolved) == {*STUBBED_CAPABILITIES, "echo"}
    assert all(cls.is_stub for _, cls in resolved.values())


def test_enabled_filter_and_unknown_name() -> None:
    result = discover_all({"stubs", "nope"})
    assert [p.name for p in result.plugins] == ["stubs"]
    assert [e.package for e in result.errors] == ["nope"]
    assert discover_all(set()).plugins == []


def test_errors_reported_without_hiding_others(fake_pkg: str) -> None:
    result = discover_all(packages=("hmap.agents", fake_pkg))
    assert {p.name for p in result.plugins} >= {"stubs", "fake_extract"}  # plus any other built-in plug-ins
    errors = {e.package.rsplit(".", 1)[-1]: e.error for e in result.errors}
    assert set(errors) == {"broken", "no_plugin_attr"}
    assert "does_not_exist_anywhere" in errors["broken"] and "PLUGIN" in errors["no_plugin_attr"]
    assert all(e.traceback for e in result.errors)
    with pytest.raises(PluginError, match="broken"):
        discover(packages=(fake_pkg,), strict=True)


def test_real_plugin_wins_over_stub(fake_pkg: str) -> None:
    plugins = discover(packages=("hmap.agents", fake_pkg))
    resolved = resolve_capabilities(plugins)
    plugin, agent_cls = resolved["document.extract"]
    assert plugin.name == "fake_extract" and agent_cls.name == "fake-extractor" and not agent_cls.is_stub
    assert resolved["review.final"][0].name == "stubs"

    rows = {r.capability: r for r in capability_table(plugins)}
    assert rows["document.extract"].status == "real" and "stubs" in rows["document.extract"].shadowed
    assert rows["review.final"].status == "stub"
    assert rows["document.summarise"].status == "real"

    runs = {cls.name: caps for _, cls, caps in agents_to_run(plugins)}
    assert "stub-document-extract" not in runs  # the stub yielded its only capability
    assert set(runs["fake-extractor"]) == {"document.extract", "document.summarise"}
    assert runs["stub-review-final"] == ("review.final",)


def test_missing_capability_listed() -> None:
    rows = capability_table([], expected=["review.final"])
    assert [(r.capability, r.status, r.plugin) for r in rows] == [("review.final", "missing", None)]


class _A(BaseAgent):
    name = "a"
    capabilities = ("x.run",)


class _B(BaseAgent):
    name = "b"
    capabilities = ("x.run",)


def test_equal_priority_conflict() -> None:
    with pytest.raises(CapabilityConflict, match=r"x\.run"):
        resolve_capabilities([Plugin(name="p1", agents=[_A]), Plugin(name="p2", agents=[_B])])
    winner = resolve_capabilities([Plugin(name="p1", agents=[_A], priority=5), Plugin(name="p2", agents=[_B])])
    assert winner["x.run"][0].name == "p2"


def test_duplicate_plugin_name_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = f"hmap_fake_dupes_{uuid.uuid4().hex[:8]}"
    _write(tmp_path, f"{pkg}/__init__.py")
    for sub in ("one", "two"):
        _write(tmp_path, f"{pkg}/{sub}/__init__.py")
        _write(tmp_path, f"{pkg}/{sub}/plugin.py", REAL_PLUGIN.format(name="same"))
    monkeypatch.syspath_prepend(str(tmp_path))
    result = discover_all(packages=(pkg,))
    assert [p.name for p in result.plugins] == ["same"]
    assert len(result.errors) == 1 and "duplicate plug-in name" in result.errors[0].error


def test_validate_plugin() -> None:
    class NoCaps(BaseAgent):
        name = "nocaps"

    class BadCap(BaseAgent):
        name = "badcap"
        capabilities = ("Bad Cap",)

    for agents in ([NoCaps], [BadCap], [_A, _A], [object]):
        with pytest.raises(PluginError):
            validate_plugin(Plugin(name="p", agents=agents))  # type: ignore[list-item]
    validate_plugin(Plugin(name="ok", agents=[_A]))

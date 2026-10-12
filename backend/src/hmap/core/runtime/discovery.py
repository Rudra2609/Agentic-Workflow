"""Plug-in discovery (Sprint 1 item 1.18, §3.5). Walks ``hmap.agents.*`` with ``pkgutil``, imports each
``<pkg>.plugin`` and reads its module-level ``PLUGIN``. Nobody edits a shared registry file.

- A sub-package without ``plugin.py`` is skipped silently (helpers, shared code).
- A plug-in that fails to import, is invalid, or reuses another plug-in's name is reported in
  ``DiscoveryResult.errors`` (and logged) without hiding the others; ``discover(strict=True)`` raises instead.
- ``resolve_capabilities`` picks, per capability, the agent of the highest-priority plug-in (stubs use priority 0,
  so a real plug-in for the same capability wins). Equal priority from two plug-ins is a configuration error.
- ``capability_table`` lists each capability as real / stub / missing (feeds the "no silent stubs" check).
"""

import importlib
import importlib.util
import pkgutil
import traceback
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from hmap.core.contracts import STUBBED_CAPABILITIES, CapabilityDescriptor
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import BaseAgent
from hmap.core.tracing import get_logger

AGENTS_PACKAGE = "hmap.agents"
_log = get_logger("hmap.runtime.discovery")


class PluginError(HmapError):
    code = ErrorCode.INTERNAL_AGENT


class CapabilityConflict(PluginError):
    pass


@dataclass(frozen=True)
class PluginLoadError:
    package: str
    error: str
    traceback: str = ""

    def __str__(self) -> str:
        return f"{self.package}: {self.error}"


@dataclass
class DiscoveryResult:
    plugins: list[Plugin] = field(default_factory=list)
    errors: list[PluginLoadError] = field(default_factory=list)


def discover_all(enabled: set[str] | None = None, *,
                 packages: Sequence[str] = (AGENTS_PACKAGE,)) -> DiscoveryResult:
    """Import every ``<package>.<sub>.plugin`` and collect its ``PLUGIN``; ``enabled`` filters by plug-in name."""
    result = DiscoveryResult()
    seen: dict[str, str] = {}
    for package in packages:
        try:
            root = importlib.import_module(package)
        except Exception as exc:
            result.errors.append(_load_error(package, exc))
            continue
        for info in sorted(pkgutil.iter_modules(getattr(root, "__path__", []), prefix=f"{package}."),
                           key=lambda i: i.name):
            if not info.ispkg:
                continue
            plugin = _load_one(info.name, result.errors)
            if plugin is None:
                continue
            if plugin.name in seen:
                result.errors.append(PluginLoadError(
                    info.name, f"duplicate plug-in name {plugin.name!r} (already defined by {seen[plugin.name]})"))
                continue
            seen[plugin.name] = info.name
            if enabled is None or plugin.name in enabled:
                result.plugins.append(plugin)
    for name in sorted((enabled or set()) - set(seen)):
        result.errors.append(PluginLoadError(name, "enabled in HMAP_PLUGINS but no such plug-in was found"))
    for err in result.errors:
        _log.error("plug-in not loaded", package=err.package, error=err.error)
    return result


def discover(enabled: set[str] | None = None, *, packages: Sequence[str] = (AGENTS_PACKAGE,),
             strict: bool = False) -> list[Plugin]:
    result = discover_all(enabled, packages=packages)
    if strict and result.errors:
        raise PluginError("plug-in discovery failed:\n" + "\n".join(f"  - {e}" for e in result.errors))
    return result.plugins


def _load_error(package: str, exc: BaseException) -> PluginLoadError:
    return PluginLoadError(package, f"{type(exc).__name__}: {exc}",
                           "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def _load_one(pkg_name: str, errors: list[PluginLoadError]) -> Plugin | None:
    try:
        if importlib.util.find_spec(f"{pkg_name}.plugin") is None:
            return None  # not a plug-in package
        module = importlib.import_module(f"{pkg_name}.plugin")
        plugin = getattr(module, "PLUGIN", None)
        if not isinstance(plugin, Plugin):
            raise PluginError(f"{pkg_name}.plugin must define PLUGIN = Plugin(...), got {type(plugin).__name__}")
        validate_plugin(plugin)
    except Exception as exc:
        errors.append(_load_error(pkg_name, exc))
        return None
    return plugin


def validate_plugin(plugin: Plugin) -> None:
    if not plugin.name:
        raise PluginError("plug-in has an empty name")
    names: set[str] = set()
    for agent_cls in plugin.agents:
        if not (isinstance(agent_cls, type) and issubclass(agent_cls, BaseAgent)):
            raise PluginError(f"plug-in {plugin.name}: {agent_cls!r} is not a BaseAgent subclass")
        if not agent_cls.name:
            raise PluginError(f"plug-in {plugin.name}: {agent_cls.__name__}.name is empty")
        if agent_cls.name in names:
            raise PluginError(f"plug-in {plugin.name}: duplicate agent name {agent_cls.name!r}")
        names.add(agent_cls.name)
        if not agent_cls.capabilities:
            raise PluginError(f"plug-in {plugin.name}: {agent_cls.__name__} declares no capabilities")
        for cap in agent_cls.capabilities:
            try:
                CapabilityDescriptor(name=cap)
            except ValidationError as exc:
                raise PluginError(f"plug-in {plugin.name}: invalid capability name {cap!r}") from exc


Resolution = tuple[Plugin, type[BaseAgent]]


def _providers(plugins: Iterable[Plugin]) -> dict[str, list[Resolution]]:
    out: dict[str, list[Resolution]] = {}
    for plugin in plugins:
        for agent_cls in plugin.agents:
            for cap in agent_cls.capabilities:
                out.setdefault(cap, []).append((plugin, agent_cls))
    for providers in out.values():
        providers.sort(key=lambda r: (-r[0].priority, r[0].name))
    return out


def resolve_capabilities(plugins: Iterable[Plugin]) -> dict[str, Resolution]:
    """capability -> (plugin, agent class) of the highest-priority provider."""
    resolved: dict[str, Resolution] = {}
    for cap, providers in sorted(_providers(plugins).items()):
        best = providers[0]
        ties = [r for r in providers[1:] if r[0].priority == best[0].priority]
        if ties:
            who = ", ".join(f"{p.name}.{a.__name__}" for p, a in [best, *ties])
            raise CapabilityConflict(f"capability {cap!r} is provided at priority {best[0].priority} by: {who}; "
                                     "raise one plug-in's priority or disable one via HMAP_PLUGINS")
        resolved[cap] = best
    return resolved


def agents_to_run(plugins: Iterable[Plugin]) -> list[tuple[Plugin, type[BaseAgent], tuple[str, ...]]]:
    """One entry per agent class that won at least one capability, with the capabilities it should serve."""
    won: dict[type[BaseAgent], tuple[Plugin, list[str]]] = {}
    for cap, (plugin, agent_cls) in resolve_capabilities(plugins).items():
        won.setdefault(agent_cls, (plugin, []))[1].append(cap)
    return [(plugin, cls, tuple(caps)) for cls, (plugin, caps) in won.items()]


Status = Literal["real", "stub", "missing"]


@dataclass(frozen=True)
class CapabilityRow:
    capability: str
    status: Status
    plugin: str | None = None
    agent: str | None = None
    priority: int | None = None
    shadowed: tuple[str, ...] = ()  # plug-ins that also declare it but yielded

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "status": self.status, "plugin": self.plugin, "agent": self.agent,
                "priority": self.priority, "shadowed": list(self.shadowed)}


def capability_table(plugins: Iterable[Plugin], *,
                     expected: Iterable[str] = STUBBED_CAPABILITIES) -> list[CapabilityRow]:
    """Every declared capability (plus ``expected`` ones nobody serves, as ``missing``), sorted by name."""
    plugins = list(plugins)
    providers = _providers(plugins)
    resolved = resolve_capabilities(plugins)
    rows: list[CapabilityRow] = []
    for cap in sorted(set(providers) | set(expected)):
        if cap not in resolved:
            rows.append(CapabilityRow(cap, "missing"))
            continue
        plugin, agent_cls = resolved[cap]
        rows.append(CapabilityRow(
            capability=cap, status="stub" if agent_cls.is_stub else "real", plugin=plugin.name,
            agent=agent_cls.name, priority=plugin.priority,
            shadowed=tuple(p.name for p, _ in providers[cap][1:]),
        ))
    return rows

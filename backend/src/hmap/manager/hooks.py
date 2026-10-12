"""Plug-in hook dispatch and strategy-slot resolution (Sprint 1 §3.5)."""

import logging
from collections.abc import Sequence
from typing import Any

from hmap.core.contracts import DomainEvent
from hmap.core.plugins import Hook, ManagerHandle, Plugin, ProjectStopped

log = logging.getLogger("hmap.manager.hooks")


class HookDispatcher:
    """Calls every ``Hook`` whose ``event_type`` equals the event's type (and, for ``task.*`` events with a
    ``capability`` filter, whose capability matches ``event.data['capability']``). Hooks run in plug-in priority
    order (highest first); an exception is logged and never propagates to the Manager."""

    def __init__(self, plugins: Sequence[Plugin]) -> None:
        ordered = sorted(plugins, key=lambda p: -p.priority)
        self._hooks: list[tuple[str, Hook]] = [(p.name, h) for p in ordered for h in p.manager_hooks]
        self.errors: list[tuple[str, str, BaseException]] = []   # (plugin, event_type, error) for diagnostics

    def matching(self, event: DomainEvent) -> list[tuple[str, Hook]]:
        out = []
        for plugin, h in self._hooks:
            if h.event_type != event.event_type:
                continue
            if h.capability is not None and event.event_type.startswith("task.") \
                    and event.data.get("capability") != h.capability:
                continue
            out.append((plugin, h))
        return out

    async def dispatch(self, event: DomainEvent, handle: ManagerHandle) -> None:
        for plugin, h in self.matching(event):
            try:
                await h.fn(event, handle)
            except ProjectStopped:
                log.info("hook %s of plugin %s skipped on %s: project was stopped",
                         getattr(h.fn, "__name__", h.fn), plugin, event.event_type)
            except Exception as exc:
                self.errors.append((plugin, event.event_type, exc))
                log.exception("hook %s of plugin %s failed on %s", getattr(h.fn, "__name__", h.fn), plugin,
                              event.event_type)


def resolve_strategy(plugins: Sequence[Plugin], slot: str, default: Any) -> Any:
    """The highest-priority plug-in that provides ``slot`` (non-None) wins; a class is instantiated."""
    for p in sorted(plugins, key=lambda p: -p.priority):
        impl = p.provides.get(slot)
        if impl is not None:
            return impl() if isinstance(impl, type) else impl
    return default

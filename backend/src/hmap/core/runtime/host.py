"""Dev agent host (Sprint 1 item 1.18): ``hmap-agents`` runs every discovered agent in ONE asyncio process.

    hmap-agents list [--json]          capability table (real / stub / missing) + plug-in load errors
    hmap-agents run --all              every plug-in enabled by HMAP_PLUGINS (default: all)
    hmap-agents run --only research    a single plug-in (chaos tests, debugging)

Each resolved agent class gets its own ``AgentWorker`` (own consumers, heartbeat and registry lease), so behaviour
is the same as one process per agent. Concrete bus / LLM / store implementations are imported lazily by the
``make_*`` factories, so this module imports even before those implementations exist.

Note: with ``HMAP_BUS=memory`` the bus lives inside this process, so agents can only talk to a Manager running in
the same process (use ``run_agents(..., bus=shared_bus)``); a separate Manager process needs ``HMAP_BUS=rabbitmq``.
"""

import argparse
import asyncio
import contextlib
import importlib
import json
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hmap.core.bus.base import Bus
from hmap.core.bus.stores import InboxStore
from hmap.core.config import Settings
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.llm.base import LLMClient
from hmap.core.plugins import Plugin
from hmap.core.runtime.discovery import agents_to_run, capability_table, discover_all
from hmap.core.runtime.worker import AgentWorker, Refiner
from hmap.core.tracing import configure_logging, get_logger
from hmap.services.artifact.base import ArtifactStore
from hmap.services.context.base import ContextStore

_log = get_logger("hmap.runtime.host")


# ---------------------------------------------------------------------- factories (lazy imports)


def _import_attr(module: str, *names: str) -> Any:
    mod = importlib.import_module(module)
    for name in names:
        if hasattr(mod, name):
            return getattr(mod, name)
    raise ImportError(f"{module} has none of {names}")


def make_bus(settings: Settings) -> Bus:
    try:
        if settings.bus == "rabbitmq":
            cls = _import_attr("hmap.core.bus.rabbitmq", "RabbitBus", "RabbitMQBus")
            bus: Bus = cls(settings.rabbitmq_url)
            return bus
        cls = _import_attr("hmap.core.bus.memory", "InMemoryBus")
        bus = cls()
        return bus
    except ImportError as exc:
        raise HmapError(f"bus {settings.bus!r} is not available yet: {exc}", code=ErrorCode.INTERNAL_AGENT) from exc


class _UnavailableLLM:
    """Placeholder until the LLM gateway exists: stubs never call it; real agents get a clear error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _fail(self) -> HmapError:
        return HmapError(f"LLM gateway unavailable: {self.reason}", code=ErrorCode.INTERNAL_AGENT, retryable=False)

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise self._fail()

    async def classify(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    async def read_images(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()


def make_llm(settings: Settings) -> LLMClient:
    try:
        build = _import_attr("hmap.core.llm", "build_llm")
    except ImportError as exc:
        _log.warning("LLM gateway not available; agents that call the LLM will fail", error=str(exc))
        return _UnavailableLLM(str(exc))
    llm: LLMClient = build(settings)
    return llm


def llm_for_plugin(llm: LLMClient, plugin: str) -> LLMClient:
    """The gateway binds each plug-in to its own replay-cache folder (``Gateway.for_plugin``); duck-typed."""
    bind = getattr(llm, "for_plugin", None)
    if bind is None:
        return llm
    bound: LLMClient = bind(plugin)
    return bound


def make_artifacts(settings: Settings) -> ArtifactStore:
    from hmap.services.artifact.local import LocalFSArtifactStore

    return LocalFSArtifactStore(settings.artifact_root)


def make_contexts(settings: Settings) -> ContextStore:
    from hmap.services.context.memory import InMemoryContextStore  # Postgres-backed store in Phase B

    return InMemoryContextStore()


class _ProcessInbox:
    """Fallback ``InboxStore`` (one process, in memory) used if the shared implementation is not importable."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    async def seen(self, consumer_id: str, message_id: str) -> bool:
        return (consumer_id, message_id) in self._seen

    async def record(self, consumer_id: str, message_id: str) -> bool:
        key = (consumer_id, message_id)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def make_inbox(settings: Settings) -> InboxStore:
    try:
        cls = _import_attr("hmap.core.bus.inbox", "InMemoryInboxStore")
    except ImportError:
        return _ProcessInbox()
    inbox: InboxStore = cls()
    return inbox


# ---------------------------------------------------------------------- running


@dataclass
class HostDeps:
    bus: Bus
    llm: LLMClient
    artifacts: ArtifactStore
    contexts: ContextStore
    inbox: InboxStore
    owns_bus: bool = True


@dataclass
class AgentHost:
    plugins: list[Plugin]
    deps: HostDeps
    heartbeat_s: float = 5.0
    drain_timeout_s: float = 30.0
    workers: list[AgentWorker] = field(default_factory=list)

    def build_workers(self) -> list[AgentWorker]:
        refiners = resolve_refiners(self.plugins)
        self.workers = [
            AgentWorker(agent_cls(), self.deps.bus, llm_for_plugin(self.deps.llm, plugin.name), self.deps.artifacts,
                        self.deps.contexts, self.deps.inbox, heartbeat_s=self.heartbeat_s, capabilities=caps,
                        plugin=plugin.name, drain_timeout_s=self.drain_timeout_s, refiners=refiners)
            for plugin, agent_cls, caps in agents_to_run(self.plugins)
        ]
        return self.workers

    async def start(self) -> None:
        if self.deps.owns_bus:
            await self.deps.bus.start()
        if not self.workers:
            self.build_workers()
        for worker in self.workers:
            await worker.start()
            _log.info("agent running", agent=worker.agent.name, agent_id=worker.agent_id,
                      capabilities=list(worker.capabilities), plugin=worker.plugin, stub=worker.agent.is_stub)

    async def stop(self, reason: str = "shutdown") -> None:
        await asyncio.gather(*(w.stop(reason) for w in self.workers), return_exceptions=True)
        if self.deps.owns_bus:
            with contextlib.suppress(Exception):
                await self.deps.bus.close()


def resolve_refiners(plugins: Sequence[Plugin]) -> dict[str, Refiner]:
    """capability -> the refine adapter of the highest-priority plug-in that registered one (``Plugin.refiners``,
    Sprint 4 plan D1). Plug-ins disabled by ``HMAP_PLUGINS`` are not in ``plugins``, so their adapters are off."""
    out: dict[str, tuple[int, Refiner]] = {}
    for plugin in plugins:
        for capability, adapter in plugin.refiners.items():
            current = out.get(capability)
            if current is None or plugin.priority > current[0]:
                out[capability] = (plugin.priority, Refiner(plugin=plugin.name, adapter=adapter))
    return {cap: refiner for cap, (_, refiner) in out.items()}


def build_deps(settings: Settings) -> HostDeps:
    return HostDeps(bus=make_bus(settings), llm=make_llm(settings), artifacts=make_artifacts(settings),
                    contexts=make_contexts(settings), inbox=make_inbox(settings))


def select_enabled(settings: Settings, only: str | None) -> set[str] | None:
    return {only} if only else settings.enabled_plugins()


async def run_agents(settings: Settings, *, only: str | None = None, deps: HostDeps | None = None,
                     stop_event: asyncio.Event | None = None, heartbeat_s: float = 5.0) -> AgentHost:
    """Discover, start one worker per resolved agent, wait for ``stop_event`` (or SIGINT/SIGTERM), then drain."""
    result = discover_all(select_enabled(settings, only))
    if not result.plugins:
        raise HmapError("no plug-ins to run" + "".join(f"\n  - {e}" for e in result.errors))
    host = AgentHost(result.plugins, deps or build_deps(settings), heartbeat_s=heartbeat_s)
    stop = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    if stop_event is None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop.set)
                installed.append(sig)
    try:
        await host.start()
        await stop.wait()
    finally:
        await host.stop()
        for sig in installed:
            loop.remove_signal_handler(sig)
    return host


# ---------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hmap-agents", description="Run hmap agent plug-ins in one process.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run agents")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--all", action="store_true", help="every plug-in enabled by HMAP_PLUGINS")
    which.add_argument("--only", metavar="PLUGIN", help="a single plug-in by name")
    run.add_argument("--heartbeat-s", type=float, default=5.0)
    lst = sub.add_parser("list", help="print the capability table (real / stub / missing)")
    lst.add_argument("--json", action="store_true")
    return parser


def format_table(rows: Sequence[dict[str, Any]]) -> str:
    cols = ["capability", "status", "plugin", "agent", "priority", "shadowed"]
    cells = [[", ".join(r[c]) if isinstance(r[c], list) else ("" if r[c] is None else str(r[c])) for c in cols]
             for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    lines = ["  ".join(c.upper().ljust(w) for c, w in zip(cols, widths, strict=True))]
    lines += ["  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip() for row in cells]
    return "\n".join(lines)


def cmd_list(settings: Settings, *, as_json: bool = False) -> int:
    result = discover_all(settings.enabled_plugins())
    rows = [r.to_dict() for r in capability_table(result.plugins)]
    errors = [{"package": e.package, "error": e.error} for e in result.errors]
    if as_json:
        print(json.dumps({"capabilities": rows, "errors": errors}, indent=2))
    else:
        print(format_table(rows))
        for e in errors:
            print(f"ERROR {e['package']}: {e['error']}", file=sys.stderr)
    return 1 if errors else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_json)
    if args.command == "list":
        return cmd_list(settings, as_json=args.json)
    if settings.bus == "memory":
        _log.warning("HMAP_BUS=memory: agents only see a Manager in this same process; use rabbitmq across processes")
    from hmap import obs

    obs.configure(service_name="hmap-agents", endpoint=settings.otel_endpoint or "")
    obs.metrics.set_process_name("hmap-agents")
    if settings.metrics_port:
        obs.metrics.serve(settings.metrics_port)
    try:
        asyncio.run(run_agents(settings, only=args.only, heartbeat_s=args.heartbeat_s))
    except HmapError as exc:
        print(f"hmap-agents: {exc}", file=sys.stderr)
        return 2
    finally:
        obs.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

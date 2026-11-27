"""The model router (item 11.7): the ``llm_provider`` strategy (``RouteStrategy``) the gateway asks before every live
chat call (``HMAP_ROUTER=on``, the default since the live evaluation, docs/members/11/eval.md §4).
``HMAP_ROUTER=off`` answers ``None``, and the gateway does exactly what it did before Sprint 11.

Inside the team's policy (every chat role cloud-first, then the local model; ``DEFAULT_CLOUD_ROLE_MAP``) the router
decides **the order of the routes and the local fallback**, never a provider the policy does not list:

1. **per-task overrides** ``HMAP_ROUTE_OVERRIDES=plugin:role=model`` (``*`` = any plug-in; ``provider:model`` = that
   cloud route only, else a local model with no cloud);
2. **rules**: a route that rejected a prompt of this size before is skipped (learned, per model); a route that is
   *saturated* goes last (its provider has no usable key right now, it answered 429 in the last minute with no
   success since, or it already had its free-tier request budget this minute); ``cloud_ok=false`` → local only;
3. **benchmark table**: among the unsaturated routes, a route whose measured quality for this role is more than
   ``QUALITY_MARGIN`` better goes first (``samples/models/bench/table.json``, written by the benchmark harness);
   otherwise the configured order stands;
4. **fallback chain**: the cloud routes, then the local model: the role map's model if it is installed and fits;
   the model already loaded if it is within ``SWAP_MARGIN`` of it for this role (no swap); else the best installed
   model that fits. Local calls go through the scheduler (priority, swap grouping, admission).

Every decision is a ``RouteDecision`` with a one-line reason, logged with its outcome (``route_decisions``, 7 days,
no prompt or answer text) and streamed to the Models tab.
"""

import asyncio
import contextvars
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hmap.agents.models.hardware import Hardware, feasible, profile, snapshot_specs
from hmap.agents.models.model import ModelRow, RouteRecord
from hmap.agents.models.store import MemoryModelStore, ModelStore
from hmap.core.config import CLOUD_PROVIDERS, Settings
from hmap.core.contracts.domain import RouteDecision
from hmap.core.plugins import RouteOutcome, RoutePlan, RouteQuery
from hmap.core.tracing import get_logger

log = get_logger("hmap.models.router")

TABLE_PATH = Path(__file__).resolve().parents[5] / "samples" / "models" / "bench" / "table.json"
QUALITY_MARGIN = 0.05        # 88-item sets: differences below ~0.01-0.03 are noise (samples/models/README.md)
SWAP_MARGIN = 0.02           # keep the loaded model if it is this close (a swap costs 4-10 s)
SATURATION_WINDOW_S = 60.0
# Free-tier requests per minute per key (the providers' published limits for the default models, checked
# 2026-10-12; an assumption the 429s correct: a route that answers 429 is treated as saturated anyway)
RPM_PER_KEY = {"groq": 30, "gemini": 10}
REFRESH_S = 30.0
FLUSH_S = 1.0

MEMORY_STORE = MemoryModelStore()       # one process: the API reads the same store the router writes
_current: contextvars.ContextVar[RouteRecord | None] = contextvars.ContextVar("hmap_route_record", default=None)


def load_table(path: Path = TABLE_PATH) -> dict[str, dict[str, float]]:
    """role -> model id -> quality (0-1) from the benchmark harness; ``{}`` before any benchmark."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {role: {m: float(q) for m, q in models.items()} for role, models in data.get("roles", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


@dataclass
class RouteStats:
    """What the key pool told us about each ``provider:model`` route recently (in this process)."""

    events: dict[str, deque[tuple[float, str]]] = field(default_factory=lambda: defaultdict(deque))
    rejected_at: dict[str, int] = field(default_factory=dict)      # smallest prompt estimate it rejected

    def add(self, route: str, outcome: str, now: float) -> None:
        q = self.events[route]
        q.append((now, outcome))
        while q and now - q[0][0] > 5 * SATURATION_WINDOW_S:
            q.popleft()

    def reject(self, route: str, est_tokens: int) -> None:
        if est_tokens > 0:
            self.rejected_at[route] = min(est_tokens, self.rejected_at.get(route, est_tokens))

    def recent(self, route: str, now: float, window: float = SATURATION_WINDOW_S) -> list[str]:
        return [o for t, o in self.events.get(route, ()) if now - t <= window]

    def rate_limited_since_ok(self, route: str, now: float) -> bool:
        last_429 = last_ok = -1.0
        for t, o in self.events.get(route, ()):
            if now - t > SATURATION_WINDOW_S:
                continue
            if o == "rate_limited":
                last_429 = t
            elif o == "ok":
                last_ok = t
        return last_429 > last_ok

    def snapshot(self, now: float) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for route, q in self.events.items():
            recent = [o for t, o in q if now - t <= SATURATION_WINDOW_S]
            out[route] = {"last_minute": len(recent), "ok": recent.count("ok"),
                          "rate_limited": recent.count("rate_limited"), "rejected_at": self.rejected_at.get(route)}
        return out


class ModelRouter:
    def __init__(self, settings: Settings | None = None, *, store: ModelStore | None = None,
                 table: dict[str, dict[str, float]] | None = None, local: dict[str, ModelRow] | None = None,
                 hardware: Hardware | None = None, scheduler: Any = None, clock: Any = time.monotonic,
                 background: bool = True) -> None:
        self.settings = settings or Settings()
        self.store: ModelStore | None = store
        self.table = table if table is not None else load_table()
        self.local: dict[str, ModelRow] | None = local          # None = not known (Ollama never answered)
        self.hardware = hardware
        self.specs = snapshot_specs()
        self.scheduler = scheduler
        self.servers: dict[str, Any] = {}                       # mlx / llamacpp backends (OpenAI-compatible)
        self.clock = clock
        self.stats = RouteStats()
        self.background = background
        self.decisions = 0
        self._pending: dict[str, RouteRecord] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False

    # ------------------------------------------------------------------ slot protocol
    def configure(self, settings: Settings) -> None:
        """Called by the platform when it builds the gateway: the local backends and the scheduler."""
        self.settings = settings
        if not self.enabled:
            return
        from hmap.agents.models.backends.local import OllamaBackend, OpenAILocalBackend
        from hmap.agents.models.scheduler import Scheduler

        if self.scheduler is None:
            self.scheduler = Scheduler(OllamaBackend(settings.ollama_base_url, num_ctx=settings.ollama_num_ctx),
                                       specs=self._spec, hardware=lambda: self.hardware,
                                       slots=settings.llm_max_concurrency)
        for name, url in (("mlx", settings.mlx_base_url), ("llamacpp", settings.llamacpp_base_url)):
            if url and name not in self.servers:
                self.servers[name] = OpenAILocalBackend(name, url)

    def _spec(self, model: str) -> dict[str, Any] | None:
        row = (self.local or {}).get(model)
        return self.specs.get(model) or (row.details if row is not None and row.details else None)

    @property
    def enabled(self) -> bool:
        return self.settings.router == "on"

    def decide(self, query: RouteQuery) -> RoutePlan | None:
        if not self.enabled:
            return None
        self._start_background()
        now = self.clock()
        configured = [tuple(r) for r in query.default_routes]
        cloud: list[tuple[str, str]] = list(configured)          # type: ignore[arg-type]
        local_model = query.default_model
        notes: list[str] = []
        rule = "configured order"
        override = (self.settings.route_overrides.get(f"{query.plugin}:{query.role}")
                    or self.settings.route_overrides.get(f"*:{query.role}"))
        if override:
            provider, sep, model = override.partition(":")
            if sep and provider in CLOUD_PROVIDERS:
                cloud, rule = [(provider, model)], "override"
            else:
                cloud, local_model, rule = [], override, "override"
            notes.append(f"override {query.plugin}:{query.role}={override}")
        elif not query.cloud_allowed:
            cloud = []
        else:
            cloud, rule = self._order(query, cloud, now, notes)
        local_model, local_note = self._local_choice(query, local_model)
        if local_note:
            notes.append(local_note)
        local_step = (local_model if local_model and local_model.partition(":")[0] in ("mlx", "llamacpp")
                      else f"ollama:{local_model}") if local_model else None
        chain = [f"{p}:{m}" for p, m in cloud] + ([local_step] if local_step else [])
        first = chain[0] if chain else "none:none"
        backend, _, model = first.partition(":")
        reason = "; ".join(notes) or ("the configured order" if cloud else "local model")
        rec = RouteRecord(decision=RouteDecision(role=query.role, model=model or "none", backend=backend,
                                                 params={"chain": chain}, reason=reason[:500]),
                          plugin=query.plugin, est_tokens=query.est_tokens, chain=chain, rule=rule)
        _current.set(rec)
        self.decisions += 1
        self._queue(rec)
        server = local_model.partition(":")[0] if local_model and ":" in local_model else ""
        if server in self.servers:                    # an MLX / llama.cpp model (e.g. a LoRA adapter, item 11.12)
            local: Any = self.servers[server]
        else:
            local = self.scheduler.provider() if self.scheduler is not None and local_model else None
        return RoutePlan(cloud_routes=None if cloud == configured else cloud,
                         local_model=None if local_model == query.default_model else local_model,
                         local=local, reason=reason, decision_id=rec.id)

    def observe(self, query: RouteQuery, plan: RoutePlan | None, outcome: RouteOutcome) -> None:
        rec = _current.get()
        if rec is None or plan is None or rec.id != plan.decision_id:
            return
        rec.answered_by = f"{outcome.provider}:{outcome.model}" if outcome.ok else None
        rec.ok, rec.latency_s = outcome.ok, round(outcome.latency_s, 4)
        rec.input_tokens, rec.output_tokens, rec.error = outcome.input_tokens, outcome.output_tokens, outcome.error
        self._queue(rec)
        _current.set(None)

    def observe_attempt(self, provider: str, model: str, role: str, outcome: str, latency_s: float) -> None:
        route = f"{provider}:{model}"
        self.stats.add(route, outcome, self.clock())
        rec = _current.get()
        if rec is not None:
            rec.attempts += 1
            rec.rate_limited += outcome == "rate_limited"
            if outcome == "rejected":
                self.stats.reject(route, rec.est_tokens)

    # ------------------------------------------------------------------ policy
    def saturated(self, provider: str, model: str, pool: dict[str, int], now: float) -> str | None:
        route = f"{provider}:{model}"
        if pool and pool.get(provider, 0) == 0:
            return f"{provider}: no key usable right now"
        if self.stats.rate_limited_since_ok(route, now):
            return f"{route} answered 429 in the last minute"
        budget = RPM_PER_KEY.get(provider)
        keys = pool.get(provider, 0)
        if budget and keys and len(self.stats.recent(route, now)) >= budget * keys:
            return f"{route} used its {budget}/min per key budget"
        return None

    def _order(self, query: RouteQuery, routes: list[tuple[str, str]], now: float,
               notes: list[str]) -> tuple[list[tuple[str, str]], str]:
        kept = []
        for p, m in routes:
            limit = self.stats.rejected_at.get(f"{p}:{m}")
            if limit is not None and query.est_tokens >= 0.9 * limit:
                notes.append(f"skipped {p}:{m}: rejected a ~{limit}-token prompt before")
            else:
                kept.append((p, m))
        scores = self.table.get(query.role, {})
        known = [scores.get(f"{p}:{m}") for p, m in kept]
        use_quality = (len(kept) > 1 and all(s is not None for s in known)
                       and max(known) - min(known) > QUALITY_MARGIN)  # type: ignore[type-var, operator]
        sat = {r: self.saturated(r[0], r[1], query.pool, now) for r in kept}
        ordered = sorted(enumerate(kept), key=lambda ir: (sat[ir[1]] is not None,
                                                          -(scores.get(f"{ir[1][0]}:{ir[1][1]}", 0.0))
                                                          if use_quality else 0.0, ir[0]))
        out = [r for _, r in ordered]
        for r in out:
            if sat[r]:
                notes.append(f"{r[0]}:{r[1]} last ({sat[r]})")
        if use_quality and out and out[0] != kept[0] and not sat[out[0]]:
            notes.append(f"{out[0][0]}:{out[0][1]} first: best measured {query.role} quality "
                         f"({scores[f'{out[0][0]}:{out[0][1]}']:.2f})")
        rule = ("table" if use_quality and out != kept else "rules") if out != routes else "configured order"
        return out, rule

    def _local_choice(self, query: RouteQuery, wanted: str | None) -> tuple[str | None, str]:
        """The local step of the chain. Unknown machine state (Ollama never answered) keeps the role map."""
        if self.local is None or not self.local:
            return wanted, ""
        hw = self.hardware
        usable = {m: r for m, r in self.local.items()
                  if r.spec.status != "disabled" and "embed" not in m and "embed" not in r.spec.roles_ok}
        scores = self.table.get(query.role, {})
        ctx = max(8192, query.est_tokens)

        def fits(model: str) -> bool:
            return hw is None or feasible(model, self._spec(model), hw, ctx=ctx).fit != "does_not_fit"

        if wanted in usable and fits(wanted):
            if hw is not None:
                for loaded in hw.resident:
                    if loaded != wanted and loaded in usable and loaded in scores and wanted in scores \
                            and scores[loaded] >= scores[wanted] - SWAP_MARGIN:
                        return loaded, f"local {loaded}: already loaded, within {SWAP_MARGIN} of {wanted} (no swap)"
            return wanted, ""
        candidates = [m for m in usable if fits(m)]
        if not candidates:
            return wanted, f"no installed local model fits; kept {wanted}"
        best = max(candidates, key=lambda m: (scores.get(m, 0.0), -(usable[m].spec.mem_gb or 0)))
        why = "not installed" if wanted not in usable else "does not fit now"
        return best, f"local {best}: {wanted} {why}"

    # ------------------------------------------------------------------ background: machine state + log flush
    def _start_background(self) -> None:
        if self._started or not self.background:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._started = True
        self._tasks = [loop.create_task(self._flusher()), loop.create_task(self._refresher())]

    def _queue(self, rec: RouteRecord) -> None:
        self._pending[rec.id] = rec.model_copy()

    async def _store(self) -> ModelStore:
        if self.store is None:
            if self.settings.store == "postgres":
                from hmap.agents.models.store import PgModelStore
                from hmap.db import Database

                self.store = PgModelStore(Database(self.settings.database_url, max_size=2))
            else:
                self.store = MEMORY_STORE
        return self.store

    async def flush(self) -> int:
        if not self._pending:
            return 0
        batch, self._pending = list(self._pending.values()), {}
        await (await self._store()).add_routes(batch)
        return len(batch)

    async def _flusher(self) -> None:
        pruned = 0.0
        while True:
            await asyncio.sleep(FLUSH_S)
            try:
                await self.flush()
                if time.monotonic() - pruned > 3600:
                    await (await self._store()).prune_routes(self.settings.route_log_days)
                    pruned = time.monotonic()
            except Exception as exc:  # the log never breaks routing
                log.warning("models.router.flush_failed", error=type(exc).__name__)

    async def refresh(self) -> None:
        """Machine state: installed models (registry sync) and memory (hardware profile)."""
        from hmap.agents.models.registry import ModelRegistry

        registry = ModelRegistry(self.settings, await self._store())
        await registry.sync()
        self.local = await registry.installed_local() if registry.ollama_up else None
        self.hardware = await asyncio.to_thread(profile, self.settings.ollama_base_url, docker=False)
        self.table = load_table() or self.table

    async def _refresher(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as exc:
                log.info("models.router.refresh_failed", error=type(exc).__name__)
            await asyncio.sleep(REFRESH_S)

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self.flush()
        for server in self.servers.values():
            await server.aclose()

    def snapshot(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "decisions": self.decisions, "routes": self.stats.snapshot(self.clock()),
                "local_known": self.local is not None, "table_roles": sorted(self.table)}

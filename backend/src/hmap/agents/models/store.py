"""Where the models plug-in keeps its rows (migration 011): the registry, the route decision log, benchmark results
and fine-tune runs. :class:`MemoryModelStore` serves tests and one-process runs; :class:`PgModelStore` is used when
the platform runs on Postgres, so the API process sees the decisions the agents' process made (``make demo`` runs
them apart). Writes never fail the caller: a lost row is logged."""

import json
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from hmap.agents.models.model import BenchRow, ModelRow, RouteRecord
from hmap.core.contracts.domain import BenchmarkResult, ModelSpec, RouteDecision
from hmap.core.tracing import get_logger

log = get_logger("hmap.models.store")
MAX_MEMORY_ROUTES = 5000


class ModelStore(Protocol):
    async def upsert_models(self, rows: list[ModelRow]) -> None: ...
    async def list_models(self) -> list[ModelRow]: ...
    async def set_flags(self, model_id: str, *, pinned: bool | None = None, status: str | None = None) -> bool: ...
    async def add_routes(self, records: list[RouteRecord]) -> None: ...
    async def recent_routes(self, *, limit: int = 200, role: str | None = None,
                            plugin: str | None = None) -> list[RouteRecord]: ...
    async def prune_routes(self, days: float) -> int: ...
    async def add_bench(self, rows: list[BenchRow]) -> None: ...
    async def list_bench(self, *, set_name: str | None = None) -> list[BenchRow]: ...
    async def save_finetune(self, run: dict[str, Any]) -> None: ...
    async def list_finetune(self) -> list[dict[str, Any]]: ...


class MemoryModelStore:
    def __init__(self) -> None:
        self.models: dict[str, ModelRow] = {}
        self.routes: deque[RouteRecord] = deque(maxlen=MAX_MEMORY_ROUTES)
        self.bench: list[BenchRow] = []
        self.finetune: dict[str, dict[str, Any]] = {}

    async def upsert_models(self, rows: list[ModelRow]) -> None:
        for row in rows:
            old = self.models.get(row.spec.id)
            if old is not None:   # a person's pin / disable survives a sync
                row = row.model_copy(update={"pinned": old.pinned or row.pinned})
                if old.spec.status == "disabled":
                    row = row.model_copy(update={"spec": row.spec.model_copy(update={"status": "disabled"})})
            self.models[row.spec.id] = row

    async def list_models(self) -> list[ModelRow]:
        return sorted(self.models.values(), key=lambda r: (r.spec.backend, r.spec.id))

    async def set_flags(self, model_id: str, *, pinned: bool | None = None, status: str | None = None) -> bool:
        row = self.models.get(model_id)
        if row is None:
            return False
        update: dict[str, Any] = {}
        if pinned is not None:
            update["pinned"] = pinned
        if status is not None:
            update["spec"] = row.spec.model_copy(update={"status": status})
        self.models[model_id] = row.model_copy(update=update)
        return True

    async def add_routes(self, records: list[RouteRecord]) -> None:
        by_id = {r.id: i for i, r in enumerate(self.routes)}
        for rec in records:
            if rec.id in by_id:          # an outcome update of a logged decision
                self.routes[by_id[rec.id]] = rec
            else:
                self.routes.append(rec)

    async def recent_routes(self, *, limit: int = 200, role: str | None = None,
                            plugin: str | None = None) -> list[RouteRecord]:
        out = [r for r in reversed(self.routes)
               if (role is None or r.decision.role == role) and (plugin is None or r.plugin == plugin)]
        return out[:limit]

    async def prune_routes(self, days: float) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        keep = [r for r in self.routes if r.at >= cutoff]
        dropped = len(self.routes) - len(keep)
        self.routes = deque(keep, maxlen=MAX_MEMORY_ROUTES)
        return dropped

    async def add_bench(self, rows: list[BenchRow]) -> None:
        self.bench.extend(rows)

    async def list_bench(self, *, set_name: str | None = None) -> list[BenchRow]:
        return [r for r in self.bench if set_name is None or r.set_name == set_name]

    async def save_finetune(self, run: dict[str, Any]) -> None:
        self.finetune[str(run["id"])] = run

    async def list_finetune(self) -> list[dict[str, Any]]:
        return sorted(self.finetune.values(), key=lambda r: str(r.get("at", "")), reverse=True)


def _iso(value: Any) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds") if hasattr(value, "astimezone") else str(value)


class PgModelStore:
    """The same, on Postgres (``hmap.db.Database``)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def upsert_models(self, rows: list[ModelRow]) -> None:
        try:
            async with self.db.connection() as c:
                for row in rows:
                    await c.execute(
                        "INSERT INTO model_registry (id, spec, digest, source, pinned, resident_gb, details, last_seen)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (id) DO UPDATE SET"
                        " spec = CASE WHEN model_registry.spec->>'status' = 'disabled'"
                        "   THEN jsonb_set(EXCLUDED.spec, '{status}', '\"disabled\"') ELSE EXCLUDED.spec END,"
                        " digest = EXCLUDED.digest, source = EXCLUDED.source, resident_gb = EXCLUDED.resident_gb,"
                        " details = EXCLUDED.details, last_seen = now(),"
                        " pinned = model_registry.pinned OR EXCLUDED.pinned",
                        (row.spec.id, Jsonb(row.spec.model_dump(mode="json")), row.digest, row.source, row.pinned,
                         row.resident_gb, Jsonb(row.details)))
        except Exception as exc:
            log.warning("models.registry.write_failed", error=type(exc).__name__)

    async def list_models(self) -> list[ModelRow]:
        rows = await self.db.fetch("SELECT * FROM model_registry ORDER BY spec->>'backend', id")
        return [ModelRow(spec=ModelSpec.model_validate(r["spec"]), digest=r["digest"], source=r["source"],
                         pinned=r["pinned"], resident_gb=r["resident_gb"], details=r["details"] or {},
                         last_seen=_iso(r["last_seen"])) for r in rows]

    async def set_flags(self, model_id: str, *, pinned: bool | None = None, status: str | None = None) -> bool:
        rows = await self.db.fetch(
            "UPDATE model_registry SET pinned = COALESCE(%s, pinned),"
            " spec = CASE WHEN %s::text IS NULL THEN spec ELSE jsonb_set(spec, '{status}', to_jsonb(%s::text)) END"
            " WHERE id = %s RETURNING id", (pinned, status, status, model_id))
        return bool(rows)

    async def add_routes(self, records: list[RouteRecord]) -> None:
        try:
            async with self.db.connection() as c:
                for r in records:
                    d = r.decision
                    await c.execute(
                        "INSERT INTO route_decisions (id, at, role, plugin, model, backend, reason, rule, chain,"
                        " est_tokens, answered_by, ok, latency_s, input_tokens, output_tokens, attempts, rate_limited,"
                        " error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        " ON CONFLICT (id) DO UPDATE SET answered_by = EXCLUDED.answered_by, ok = EXCLUDED.ok,"
                        " latency_s = EXCLUDED.latency_s, input_tokens = EXCLUDED.input_tokens,"
                        " output_tokens = EXCLUDED.output_tokens, attempts = EXCLUDED.attempts,"
                        " rate_limited = EXCLUDED.rate_limited, error = EXCLUDED.error",
                        (r.id, r.at, d.role, r.plugin, d.model, d.backend, d.reason, r.rule, Jsonb(r.chain),
                         r.est_tokens, r.answered_by, r.ok, r.latency_s, r.input_tokens, r.output_tokens, r.attempts,
                         r.rate_limited, r.error))
        except Exception as exc:
            log.warning("models.routes.write_failed", error=type(exc).__name__, rows=len(records))

    async def recent_routes(self, *, limit: int = 200, role: str | None = None,
                            plugin: str | None = None) -> list[RouteRecord]:
        rows = await self.db.fetch(
            "SELECT * FROM route_decisions WHERE (%s::text IS NULL OR role = %s) AND (%s::text IS NULL OR plugin = %s)"
            " ORDER BY at DESC LIMIT %s", (role, role, plugin, plugin, limit))
        return [RouteRecord(id=r["id"], at=_iso(r["at"]), plugin=r["plugin"], est_tokens=r["est_tokens"],
                            chain=list(r["chain"] or []), rule=r["rule"], answered_by=r["answered_by"], ok=r["ok"],
                            latency_s=r["latency_s"], input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
                            attempts=r["attempts"], rate_limited=r["rate_limited"], error=r["error"],
                            decision=RouteDecision(role=r["role"], model=r["model"], backend=r["backend"],
                                                   reason=r["reason"]))
                for r in rows]

    async def prune_routes(self, days: float) -> int:
        rows = await self.db.fetch("DELETE FROM route_decisions WHERE at < now() - make_interval(secs => %s)"
                                   " RETURNING 1", (days * 86400,))
        return len(rows)

    async def add_bench(self, rows: list[BenchRow]) -> None:
        async with self.db.connection() as c:
            for row in rows:
                b = row.result
                await c.execute(
                    "INSERT INTO benchmark_results (at, run_id, set_name, model, quant, role, task, quality_score,"
                    " tok_s, ttft_s, mem_gb, n, digest, seconds, notes)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (row.at, row.run_id, row.set_name, b.model, b.quant, b.role, b.task, b.quality_score, b.tok_s,
                     b.ttft_s, b.mem_gb, row.n, row.digest, row.seconds, row.notes))

    async def list_bench(self, *, set_name: str | None = None) -> list[BenchRow]:
        rows = await self.db.fetch("SELECT * FROM benchmark_results WHERE (%s::text IS NULL OR set_name = %s)"
                                   " ORDER BY at", (set_name, set_name))
        return [BenchRow(result=BenchmarkResult(model=r["model"], quant=r["quant"], role=r["role"], task=r["task"],
                                                quality_score=r["quality_score"], tok_s=r["tok_s"], ttft_s=r["ttft_s"],
                                                mem_gb=r["mem_gb"]),
                         set_name=r["set_name"], n=r["n"], run_id=r["run_id"], digest=r["digest"],
                         seconds=r["seconds"], notes=r["notes"], at=_iso(r["at"])) for r in rows]

    async def save_finetune(self, run: dict[str, Any]) -> None:
        async with self.db.connection() as c:
            await c.execute(
                "INSERT INTO finetune_runs (id, skill, base, status, config, result) VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, config = EXCLUDED.config,"
                " result = EXCLUDED.result",
                (run["id"], run.get("skill", ""), run.get("base", ""), run.get("status", ""),
                 Jsonb(run.get("config", {})), Jsonb(json.loads(json.dumps(run.get("result", {}), default=str)))))

    async def list_finetune(self) -> list[dict[str, Any]]:
        rows = await self.db.fetch("SELECT * FROM finetune_runs ORDER BY at DESC")
        return [{**r, "at": _iso(r["at"])} for r in rows]

#!/usr/bin/env python3
"""Load / soak test (Sprint 4 item 4.20; reused by Member 11's release gate): N projects at once on the stub agents.

Each project runs an 8-step plan (research -> verify -> design -> two parallel builds -> test -> docs -> review) with
auto-approval, all projects started together (``--concurrency`` at a time). Measured: throughput (steps / s),
project latency p50 / p95 / max, failures, the largest queue depth, process RSS and free system RAM. Nothing calls a
model; the stub agents take ``--stub-delay`` seconds per step.

    cd backend
    uv run python ../infra/observability/load/soak.py --projects 40 --concurrency 20                # in memory
    HMAP_BUS=rabbitmq HMAP_STORE=postgres uv run python ../infra/observability/load/soak.py --real   # make infra-up
    uv run python ../infra/observability/load/soak.py --projects 400 --concurrency 40 --soak-minutes 10

Results: ``samples/refine/eval_results/soak-<stack>.json`` (``--out`` to change). With ``--real`` the run uses its own
Postgres database rows and RabbitMQ queues (namespaced), and the projects are deleted afterwards.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts import PlanTask, TaskGraph
from hmap.core.runtime.discovery import discover
from hmap.system import HmapSystem, SystemConfig

STEPS = [("research", "research.run", []), ("verify", "verify.claims", ["research"]),
         ("design", "code.implement", ["verify"]), ("build-a", "code.implement", ["design"]),
         ("build-b", "code.implement", ["design"]), ("test", "test.run", ["build-a", "build-b"]),
         ("docs", "docs.generate", ["test"]), ("review", "review.final", ["docs"])]
DONE = ("COMPLETED", "FAILED", "CANCELLED")


def plan(pid: str) -> TaskGraph:
    return TaskGraph(project_id=pid, tasks=[PlanTask(id=i, title=i, agent_capability=c, depends_on=d)
                                            for i, c, d in STEPS])


class Sampler:
    def __init__(self, system: HmapSystem) -> None:
        self.system, self.proc = system, psutil.Process()
        self.rss_max = 0
        self.free_min = psutil.virtual_memory().available
        self.depth_max = 0
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            self.rss_max = max(self.rss_max, self.proc.memory_info().rss)
            self.free_min = min(self.free_min, psutil.virtual_memory().available)
            try:
                self.depth_max = max(self.depth_max, max((await self.system.bus.queue_depths()).values(), default=0))
            except Exception:
                pass
            await asyncio.sleep(0.2)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()


async def one_project(system: HmapSystem, n: int, gate: asyncio.Semaphore, timeout: float) -> dict[str, Any]:
    async with gate:
        m = system.manager
        started = time.perf_counter()
        pid = await m.create_project(f"soak-{n}", auto_approve=True)
        await m.submit_graph(pid, plan(pid), require_approval=True)
        state = "?"
        while time.perf_counter() - started < timeout:
            state = (await m.get_project_record(pid)).state.value
            if state in DONE:
                break
            await asyncio.sleep(0.05)
        return {"project_id": pid, "state": state, "seconds": time.perf_counter() - started}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    stubs_only = [p for p in discover() if p.name == "stubs"]
    cfg = SystemConfig(heartbeat_s=1.0, watchdog_interval_s=0.2)
    if args.real:
        settings = Settings.from_env()
        system = HmapSystem.from_settings(settings, config=cfg, rabbit_namespace=f"soak{int(time.time())}",
                                          plugins=stubs_only)
    else:
        system = HmapSystem.in_memory(plugins=stubs_only, config=cfg)
    # several workers per capability, like several agent processes
    await system.start(with_agents=False)
    hosts = [await system.start_agents(stubs_only) for _ in range(args.agents)]
    sampler = Sampler(system)
    sampler.start()
    gate = asyncio.Semaphore(args.concurrency)
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    rounds = 0
    try:
        while True:
            rounds += 1
            batch = await asyncio.gather(*(one_project(system, len(results) + i, gate, args.timeout)
                                           for i in range(args.projects)))
            results += batch
            if not args.soak_minutes or time.perf_counter() - t0 >= args.soak_minutes * 60:
                break
    finally:
        elapsed = time.perf_counter() - t0
        await sampler.stop()
        if args.real:
            for r in results:
                try:
                    await system.manager.delete_project(r["project_id"])
                except Exception:
                    pass
        for host in hosts[:-1]:                    # system.stop() stops the last one
            await host.stop()
        await system.stop()
    secs = sorted(r["seconds"] for r in results)
    ok = [r for r in results if r["state"] == "COMPLETED"]

    def pct(p: float) -> float:
        return round(secs[min(len(secs) - 1, int(p * len(secs)))], 3) if secs else 0.0

    return {
        "stack": "rabbitmq+postgres" if args.real else "memory", "projects": len(results), "rounds": rounds,
        "concurrency": args.concurrency, "agent_sets": args.agents, "steps_per_project": len(STEPS),
        "stub_delay_s": args.stub_delay, "completed": len(ok), "failed_or_timed_out": len(results) - len(ok),
        "elapsed_s": round(elapsed, 2), "steps_per_s": round(len(ok) * len(STEPS) / elapsed, 2),
        "projects_per_min": round(len(ok) / elapsed * 60, 1),
        "latency_s": {"p50": round(statistics.median(secs), 3) if secs else 0.0, "p95": pct(0.95), "max": pct(1.0)},
        "max_queue_depth": sampler.depth_max, "rss_max_mb": round(sampler.rss_max / 2**20, 1),
        "system_free_min_gb": round(sampler.free_min / 2**30, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects", type=int, default=40, help="projects per round")
    ap.add_argument("--concurrency", type=int, default=20, help="projects running at the same time")
    ap.add_argument("--agents", type=int, default=2, help="sets of stub agents (workers per capability)")
    ap.add_argument("--stub-delay", type=float, default=0.05, help="seconds each stub step takes")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds before a project counts as failed")
    ap.add_argument("--soak-minutes", type=float, default=0.0, help="repeat rounds for this long (0 = one round)")
    ap.add_argument("--real", action="store_true", help="RabbitMQ + Postgres from the environment (make infra-up)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    import os

    os.environ["HMAP_STUB_DELAY_S"] = str(args.stub_delay)
    os.environ.setdefault("HMAP_ENV_FILE", "none")
    out = asyncio.run(run(args))
    print(json.dumps(out, indent=1))
    path = args.out or REPO_ROOT / "samples" / "refine" / "eval_results" / \
        f"soak-{'real' if args.real else 'memory'}{'-soak' if args.soak_minutes else ''}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {path}")
    return 0 if out["failed_or_timed_out"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

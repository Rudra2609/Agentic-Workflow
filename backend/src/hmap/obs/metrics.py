"""Metrics (Sprint 4 item 4.17, plan D14/D17): Prometheus counters, histograms and gauges in one registry.

- **Counters / histograms** are updated where things happen (the Manager's state changes, retries, dead letters,
  inbox dedup hits, model calls, refinement runs). They are plain in-process numbers: cheap, no network.
- **Gauges** (queue depth and age, dead-lettered tasks, task states, agent heartbeat age, RAM) are refreshed by
  :class:`Sampler` every few seconds from the bus, the task store and the registry.
- ``GET /metrics`` on the API process serves :func:`exposition`; the separate agents process
  (``hmap-agents run``) serves the same on ``HMAP_METRICS_PORT`` (default 9464) via :func:`serve`.

Labels are capability names, states, queue names, model roles / providers / models and agent ids — never project
ids, user ids, text or keys (D17; also keeps the number of series small).
"""

import asyncio
import contextlib
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import psutil
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from hmap.core.contracts.states import TaskState
from hmap.core.tracing import get_logger

log = get_logger("hmap.obs.metrics")

REGISTRY = CollectorRegistry(auto_describe=True)

# ---- the Manager
TASK_TRANSITIONS = Counter("hmap_task_transitions_total", "Task state changes, by the state entered",
                           ["capability", "state"], registry=REGISTRY)
RETRIES = Counter("hmap_task_retries_total", "Retries scheduled after a retryable failure", ["capability"],
                  registry=REGISTRY)
DEAD_LETTERS = Counter("hmap_task_dead_letters_total", "Tasks that ran out of retries (DEAD_LETTERED)",
                       ["capability"], registry=REGISTRY)
REPLAYS = Counter("hmap_task_replays_total", "Dead-lettered tasks replayed by an operator as a new execution",
                  ["capability"], registry=REGISTRY)
DEDUP_HITS = Counter("hmap_dedup_hits_total", "Deliveries skipped because they were already processed (inbox)",
                     ["consumer"], registry=REGISTRY)
REPORTS = Counter("hmap_agent_reports_total", "Agent reports the Manager consumed, by message type",
                  ["message_type"], registry=REGISTRY)
# ---- agents and models
HANDLER_SECONDS = Histogram("hmap_agent_handle_seconds", "Agent handler duration", ["capability", "outcome"],
                            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600), registry=REGISTRY)
LLM_CALLS = Counter("hmap_llm_calls_total", "Model calls through the gateway", ["role", "provider", "outcome"],
                    registry=REGISTRY)
LLM_SECONDS = Histogram("hmap_llm_latency_seconds", "Model call latency (cache hits are ~0)", ["role", "provider"],
                        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 80, 160, 320), registry=REGISTRY)
LLM_TOKENS = Counter("hmap_llm_tokens_total", "Model tokens, by direction (input/output)",
                     ["role", "provider", "direction"], registry=REGISTRY)
REFINE_RUNS = Counter("hmap_refine_runs_total", "Finished refinement loops, by capability and stop reason",
                      ["capability", "stop_reason"], registry=REGISTRY)
REFINE_ITERATIONS = Counter("hmap_refine_iterations_total", "Refinement iterations (critique + maybe revise)",
                            ["capability"], registry=REGISTRY)
REFINE_GAIN = Histogram("hmap_refine_score_gain", "Best score minus first score of a refinement loop",
                        ["capability"], buckets=(-0.2, -0.05, 0, 0.02, 0.05, 0.1, 0.2, 0.4, 1.0), registry=REGISTRY)
# ---- sampled gauges
QUEUE_DEPTH = Gauge("hmap_queue_depth", "Messages waiting in a bus queue", ["queue"], registry=REGISTRY)
QUEUE_OLDEST = Gauge("hmap_queue_oldest_ready_seconds", "Age of the oldest READY task (waiting for an agent)",
                     ["capability"], registry=REGISTRY)
TASKS = Gauge("hmap_tasks", "Tasks by state (live projects; terminal states only DEAD_LETTERED/FAILED)", ["state"],
              registry=REGISTRY)
DEAD_LETTERED = Gauge("hmap_dead_lettered_tasks", "Tasks currently DEAD_LETTERED (waiting for an operator)",
                      registry=REGISTRY)
BUS_DLQ = Gauge("hmap_bus_dlq_messages", "Messages in the bus dead-letter queue (hmap.dlq)", registry=REGISTRY)
AGENT_HEARTBEAT_AGE = Gauge("hmap_agent_heartbeat_age_seconds", "Seconds since an agent's last heartbeat",
                            ["agent_id", "agent", "state"], registry=REGISTRY)
AGENTS = Gauge("hmap_agents", "Registered agents by state", ["state"], registry=REGISTRY)
PROCESS_RSS = Gauge("hmap_process_rss_bytes", "Resident memory of this process", ["process"], registry=REGISTRY)
SYSTEM_RAM_AVAILABLE = Gauge("hmap_system_memory_available_bytes", "RAM still available on this computer",
                             registry=REGISTRY)
SYSTEM_RAM_TOTAL = Gauge("hmap_system_memory_total_bytes", "RAM of this computer", registry=REGISTRY)
SAMPLE_ERRORS = Counter("hmap_metrics_sample_errors_total", "Gauge refreshes that failed", registry=REGISTRY)

_PROCESS = psutil.Process()
_process_name = "hmap"


def exposition() -> tuple[bytes, str]:
    """The text format Prometheus scrapes, and its content type."""
    sample_process()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def set_process_name(name: str) -> None:
    global _process_name
    _process_name = name


def sample_process() -> None:
    with contextlib.suppress(Exception):
        PROCESS_RSS.labels(_process_name).set(_PROCESS.memory_info().rss)
        vm = psutil.virtual_memory()
        SYSTEM_RAM_AVAILABLE.set(vm.available)
        SYSTEM_RAM_TOTAL.set(vm.total)


# ---------------------------------------------------------------------------------------------- call-site helpers


def task_transition(capability: str, state: str) -> None:
    TASK_TRANSITIONS.labels(capability, state).inc()
    if state == "RETRY_SCHEDULED":
        RETRIES.labels(capability).inc()
    elif state == "DEAD_LETTERED":
        DEAD_LETTERS.labels(capability).inc()


def llm_call(role: str, provider: str, seconds: float, input_tokens: int, output_tokens: int, *,
             outcome: str = "ok") -> None:
    provider = provider or "unknown"
    LLM_CALLS.labels(role, provider, outcome).inc()
    LLM_SECONDS.labels(role, provider).observe(max(0.0, seconds))
    if input_tokens:
        LLM_TOKENS.labels(role, provider, "input").inc(input_tokens)
    if output_tokens:
        LLM_TOKENS.labels(role, provider, "output").inc(output_tokens)


# ---------------------------------------------------------------------------------------------- sampler


TEMP_QUEUE_PREFIX = "hmap.events.tmp."
LOST_AGENT_WINDOW_S = 600.0   # an agent that went OFFLINE keeps its heartbeat age for 10 minutes
_LIVE_STATES = ("CREATED", "READY", "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_SUBMITTED", "RETRY_SCHEDULED",
                "BLOCKED", "NEEDS_REVISION", "DEAD_LETTERED", "FAILED")


def _age(ts: Any, now: datetime) -> float:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if not isinstance(ts, datetime):
        return 0.0
    return max(0.0, (now - (ts if ts.tzinfo else ts.replace(tzinfo=UTC))).total_seconds())


class Sampler:
    """Refreshes the gauges every ``interval_s`` from the platform's own interfaces (no RabbitMQ / Postgres
    exporters needed). Errors are counted, never raised."""

    def __init__(self, *, bus: Any, store: Any, registry: Any, interval_s: float = 5.0) -> None:
        self.bus, self.store, self.registry, self.interval_s = bus, store, registry, interval_s
        self._task: asyncio.Task[None] | None = None
        self._agent_series: set[tuple[str, str, str]] = set()

    async def sample(self) -> None:
        now = datetime.now(UTC)
        try:
            depths = await self.bus.queue_depths()
            for queue, depth in depths.items():
                if not queue.startswith(TEMP_QUEUE_PREFIX):     # per-subscriber event queues come and go
                    QUEUE_DEPTH.labels(queue).set(depth)
            BUS_DLQ.set(len(await self.bus.dead_letters()))
            tasks = await self.store.list_tasks(states={TaskState(s) for s in _LIVE_STATES})
            counts = dict.fromkeys(_LIVE_STATES, 0)
            oldest: dict[str, float] = {}
            for t in tasks:
                state = str(getattr(t.state, "value", t.state))
                counts[state] = counts.get(state, 0) + 1
                if state == "READY" and not getattr(t, "needs_approval", False):
                    oldest[t.capability] = max(oldest.get(t.capability, 0.0), _age(t.updated_at, now))
            for state, n in counts.items():
                TASKS.labels(state).set(n)
            DEAD_LETTERED.set(counts.get("DEAD_LETTERED", 0))
            QUEUE_OLDEST.clear()
            for cap, age in oldest.items():
                QUEUE_OLDEST.labels(cap).set(age)
            agents = await self.registry.list()
            seen: set[tuple[str, str, str]] = set()
            by_state: dict[str, int] = {}
            for a in agents:
                state = str(getattr(a.state, "value", a.state))
                by_state[state] = by_state.get(state, 0) + 1
                age = _age(a.last_heartbeat, now)
                if state == "OFFLINE" and age > LOST_AGENT_WINDOW_S:
                    continue                     # long gone; a recently lost agent stays visible (the alert fires)
                key = (a.agent_id, a.agent_id.rsplit("-", 1)[0], state)
                seen.add(key)
                AGENT_HEARTBEAT_AGE.labels(*key).set(age)
            for stale in self._agent_series - seen:
                with contextlib.suppress(KeyError):
                    AGENT_HEARTBEAT_AGE.remove(*stale)
            self._agent_series = seen
            AGENTS.clear()
            for state, n in by_state.items():
                AGENTS.labels(state).set(n)
            sample_process()
        except Exception as exc:  # telemetry must never break the platform
            SAMPLE_ERRORS.inc()
            log.warning("metrics sample failed", error=type(exc).__name__)

    async def _loop(self) -> None:
        while True:
            await self.sample()
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="hmap-metrics-sampler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


def serve(port: int, *, addr: str = "127.0.0.1") -> bool:
    """Serve ``/metrics`` on ``addr:port`` in a background thread (the agents process). False if the port is busy."""
    from prometheus_client import start_http_server

    try:
        start_http_server(port, addr=addr, registry=REGISTRY)
    except OSError as exc:
        log.warning("metrics port busy; this process exports no metrics", port=port, error=str(exc))
        return False
    log.info("metrics served", url=f"http://{addr}:{port}/metrics")
    return True


def metric_names() -> Iterable[str]:
    return sorted({m.name for m in REGISTRY.collect()})


def now_s() -> float:
    return time.perf_counter()

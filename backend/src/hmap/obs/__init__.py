"""Observability (Member 4, Sprint 4 §5b): traces, metrics, and the helpers the platform calls at a few points.

The core only calls this facade (plan D11), and every call is cheap and safe when observability is off:

    from hmap import obs
    with obs.span("agent.handle", parent=env.traceparent, attrs={"hmap.capability": cap}) as s:
        ...
    obs.metrics.task_transition(capability, "COMPLETED")

- traces: :mod:`hmap.obs.telemetry` (OpenTelemetry -> OTLP/HTTP -> Jaeger; on when ``HMAP_OTEL_ENDPOINT`` is set)
- metrics: :mod:`hmap.obs.metrics` (Prometheus registry; ``GET /metrics`` on the API, ``HMAP_METRICS_PORT`` on the
  agents process; gauges refreshed by :class:`~hmap.obs.metrics.Sampler`)
"""

from hmap.obs import metrics
from hmap.obs.telemetry import (
    SpanHandle,
    configure,
    current_traceparent,
    enabled,
    flush,
    safe_attrs,
    shutdown,
    span,
    task_trace_id,
    task_traceparent,
    trace_id_of,
)

__all__ = [
    "SpanHandle",
    "configure",
    "current_traceparent",
    "enabled",
    "flush",
    "metrics",
    "safe_attrs",
    "shutdown",
    "span",
    "task_trace_id",
    "task_traceparent",
    "trace_id_of",
]

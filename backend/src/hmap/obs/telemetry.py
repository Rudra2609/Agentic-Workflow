"""Traces (Sprint 4 item 4.15, plan D11/D13/D17): OpenTelemetry spans exported over OTLP/HTTP to Jaeger v2.

Off unless ``HMAP_OTEL_ENDPOINT`` is set (``obs.configure`` is a no-op otherwise, and :func:`span` then yields a
no-op handle), so the core can call it unconditionally. Tests pass an in-memory exporter instead.

One trace per task: the Manager starts the trace of a task with a trace id derived from the task id
(:func:`task_trace_id`), so every execution of the task (retries, a DLQ replay) and the agent and model calls that
follow its ``traceparent`` land in the same trace — and the "why did this task fail?" view can link to it without
storing anything. Without OpenTelemetry the envelopes still carry that trace id (:func:`task_traceparent`).

Privacy (D17): span attributes are ids, sizes, states, model names, token counts and durations only — never prompts,
document text, artifact contents or keys. :func:`safe_attrs` enforces it for every attribute set through here.
"""

import contextlib
import contextvars
import hashlib
import os
import re
from collections.abc import Iterator, Mapping
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from hmap.core.tracing import get_logger

log = get_logger("hmap.obs")

Kind = Literal["internal", "server", "client", "producer", "consumer"]
_KINDS: dict[str, SpanKind] = {"internal": SpanKind.INTERNAL, "server": SpanKind.SERVER, "client": SpanKind.CLIENT,
                               "producer": SpanKind.PRODUCER, "consumer": SpanKind.CONSUMER}
_PROPAGATOR = TraceContextTextMapPropagator()
_forced_trace_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("hmap_forced_trace_id", default=None)

# Attribute values longer than this are dropped (ids, model names and states are short; text is not).
MAX_ATTR_CHARS = 200
# Key fragments that never become span attributes, whatever their value.
_FORBIDDEN_KEY = re.compile(r"prompt|content|message_text|document|quote|text$|body|payload|api_key|secret|password|"
                            r"token$", re.IGNORECASE)


class _TaskIdGenerator(IdGenerator):
    """Random ids, except a root span started by :func:`span` with ``trace_id=`` gets exactly that trace id."""

    def __init__(self) -> None:
        self._random = RandomIdGenerator()

    def generate_span_id(self) -> int:
        return self._random.generate_span_id()

    def generate_trace_id(self) -> int:
        forced = _forced_trace_id.get()
        return forced if forced else self._random.generate_trace_id()


class _State:
    provider: TracerProvider | None = None
    tracer: trace.Tracer | None = None
    service: str = "hmap"


_state = _State()


def configure(*, service_name: str, endpoint: str | None = None, exporter: SpanExporter | None = None,
              batch: bool = True) -> bool:
    """Start exporting spans. ``endpoint`` (default ``HMAP_OTEL_ENDPOINT``) is the OTLP/HTTP base URL, e.g.
    ``http://127.0.0.1:4318``; ``exporter`` replaces it (tests). Returns whether tracing is on. Idempotent: a second
    call replaces the provider (the old one is flushed and shut down)."""
    endpoint = endpoint if endpoint is not None else os.environ.get("HMAP_OTEL_ENDPOINT", "").strip()
    if exporter is None and not endpoint:
        return enabled()
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=5)
    shutdown()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name,
                                                        "service.namespace": "hmap"}),
                              id_generator=_TaskIdGenerator())
    provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=1000) if batch
                                else SimpleSpanProcessor(exporter))
    _state.provider, _state.service = provider, service_name
    _state.tracer = provider.get_tracer("hmap", "0.4")
    log.info("tracing on", service=service_name, exporter=type(exporter).__name__)
    return True


def shutdown() -> None:
    """Flush and stop the exporter (process exit, tests)."""
    provider = _state.provider
    _state.provider = _state.tracer = None
    if provider is not None:
        with contextlib.suppress(Exception):
            provider.force_flush(timeout_millis=3000)
            provider.shutdown()


def flush() -> None:
    if _state.provider is not None:
        _state.provider.force_flush(timeout_millis=3000)


def enabled() -> bool:
    return _state.tracer is not None


# ---------------------------------------------------------------------------------------------- trace ids


def task_trace_id(task_id: str) -> str:
    """The trace id (32 hex chars) every span of ``task_id`` shares."""
    digest = hashlib.sha256(f"hmap-task:{task_id}".encode()).hexdigest()[:32]
    return digest if digest.strip("0") else "1" + digest[1:]


def task_traceparent(task_id: str) -> str:
    """A W3C ``traceparent`` in the task's trace with a fresh span id (used when tracing is off)."""
    return f"00-{task_trace_id(task_id)}-{os.urandom(8).hex() or '1' * 16}-01"


def trace_id_of(traceparent: str | None) -> str | None:
    if not traceparent:
        return None
    parts = traceparent.split("-")
    return parts[1] if len(parts) == 4 and len(parts[1]) == 32 else None


# ---------------------------------------------------------------------------------------------- attributes


def safe_attrs(attrs: Mapping[str, Any] | None) -> dict[str, Any]:
    """Only short scalar values under harmless keys (D17). Lists of short scalars are kept (≤ 20 items)."""
    out: dict[str, Any] = {}
    for key, value in (attrs or {}).items():
        if value is None or _FORBIDDEN_KEY.search(key):
            continue
        if isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, str):
            if len(value) <= MAX_ATTR_CHARS:
                out[key] = value
        elif isinstance(value, list | tuple) and len(value) <= 20 and all(
                isinstance(v, bool | int | float) or (isinstance(v, str) and len(v) <= MAX_ATTR_CHARS) for v in value):
            out[key] = [str(v) if not isinstance(v, bool | int | float) else v for v in value]
    return out


# ---------------------------------------------------------------------------------------------- spans


class SpanHandle:
    """What the code inside :func:`span` may do. A no-op when tracing is off."""

    def __init__(self, otel_span: trace.Span | None = None) -> None:
        self._span = otel_span

    @property
    def recording(self) -> bool:
        return self._span is not None and self._span.is_recording()

    def set(self, key: str, value: Any) -> None:
        if self._span is not None:
            self._span.set_attributes(safe_attrs({key: value}))

    def update(self, attrs: Mapping[str, Any]) -> None:
        if self._span is not None:
            self._span.set_attributes(safe_attrs(attrs))

    def event(self, name: str, attrs: Mapping[str, Any] | None = None) -> None:
        if self._span is not None:
            self._span.add_event(name, safe_attrs(attrs))

    def error(self, exc: BaseException | str, *, code: str | None = None) -> None:
        """Mark the span failed. Only the error *type* and code are recorded, never the message (it may quote
        user text)."""
        if self._span is None:
            return
        kind = exc if isinstance(exc, str) else type(exc).__name__
        self._span.set_status(Status(StatusCode.ERROR, kind))
        self._span.set_attributes(safe_attrs({"error.type": kind, "hmap.error_code": code}))

    def traceparent(self) -> str | None:
        """This span as a W3C ``traceparent`` (to put into an envelope), or None when tracing is off."""
        if self._span is None:
            return None
        carrier: dict[str, str] = {}
        _PROPAGATOR.inject(carrier, context=trace.set_span_in_context(self._span))
        return carrier.get("traceparent")


def _parent_context(traceparent: str | None) -> Context | None:
    if not traceparent:
        return None
    ctx = _PROPAGATOR.extract({"traceparent": traceparent})
    return ctx if trace.get_current_span(ctx).get_span_context().is_valid else None


@contextlib.contextmanager
def span(name: str, *, kind: Kind = "internal", parent: str | None = None, trace_id: str | None = None,
         attrs: Mapping[str, Any] | None = None) -> Iterator[SpanHandle]:
    """A span named ``name``. Parent: ``parent`` (a ``traceparent`` from an envelope) if given, else the current
    span; with neither and ``trace_id`` set, a new root in that trace (one trace per task). Exceptions mark the span
    failed and propagate."""
    tracer = _state.tracer
    if tracer is None:
        yield SpanHandle(None)
        return
    context = _parent_context(parent)
    token = None
    if context is None and trace_id and not trace.get_current_span().get_span_context().is_valid:
        context = Context()                                  # a root ...
        token = _forced_trace_id.set(int(trace_id, 16))      # ... with the task's trace id
    try:
        with tracer.start_as_current_span(name, context=context, kind=_KINDS[kind], attributes=safe_attrs(attrs),
                                          record_exception=False, set_status_on_exception=False) as otel_span:
            if token is not None:
                _forced_trace_id.reset(token)
                token = None
            handle = SpanHandle(otel_span)
            try:
                yield handle
            except BaseException as exc:
                if not isinstance(exc, GeneratorExit):
                    handle.error(exc)
                raise
    finally:
        if token is not None:
            _forced_trace_id.reset(token)


def current_traceparent() -> str | None:
    """The active span as a ``traceparent`` (None when tracing is off or no span is active)."""
    if _state.tracer is None or not trace.get_current_span().get_span_context().is_valid:
        return None
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get("traceparent")

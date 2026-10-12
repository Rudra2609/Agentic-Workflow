"""W3C ``traceparent`` propagation (research §11) and structured JSON logging.

Every published message carries a ``traceparent``; a consumer continues the trace with :func:`child_traceparent`.
OpenTelemetry export is added in Sprint 4 (Member 4) on top of these ids.
"""

import logging
import os
import re
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_current: ContextVar[str | None] = ContextVar("hmap_traceparent", default=None)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    flags: str = "01"

    def header(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.flags}"


def _hex(nbytes: int) -> str:
    while True:
        value = os.urandom(nbytes).hex()
        if value.strip("0"):  # all-zero ids are invalid per the W3C spec
            return value


def parse_traceparent(header: str) -> TraceContext:
    m = _TRACEPARENT_RE.match(header.strip().lower())
    if not m or not m.group(1).strip("0") or not m.group(2).strip("0"):
        raise ValueError(f"invalid traceparent: {header!r}")
    return TraceContext(m.group(1), m.group(2), m.group(3))


def is_valid_traceparent(header: str | None) -> bool:
    if not header:
        return False
    try:
        parse_traceparent(header)
    except ValueError:
        return False
    return True


def new_traceparent() -> str:
    return TraceContext(_hex(16), _hex(8)).header()


def child_traceparent(parent: str | None) -> str:
    """Same trace, new span. Starts a new trace when the parent is missing or malformed."""
    if not is_valid_traceparent(parent):
        return new_traceparent()
    ctx = parse_traceparent(parent)  # type: ignore[arg-type]
    return TraceContext(ctx.trace_id, _hex(8), ctx.flags).header()


def current_traceparent() -> str | None:
    return _current.get()


def set_current_traceparent(header: str | None) -> None:
    _current.set(header)


def bind_log_context(**ids: Any) -> None:
    """Attach task/execution/message/agent ids to every log line in this async context."""
    structlog.contextvars.bind_contextvars(**{k: v for k, v in ids.items() if v is not None})


def clear_log_context() -> None:
    structlog.contextvars.clear_contextvars()


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name) if name else structlog.get_logger()

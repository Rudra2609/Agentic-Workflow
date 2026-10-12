"""Structured output helper (doc 02 §2.3): schema -> ``format`` -> pydantic validation -> up to 2 repair retries.

The helper is provider-agnostic: it takes a ``call(messages)`` coroutine that performs ONE raw completion (the
gateway passes one that goes through cache/provider with the schema as ``format``). Each repair is its own raw call,
so in record/replay every attempt is a separate, deterministic cache entry.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from hmap.core.llm.base import LLMResponse, LLMUsage, Message
from hmap.core.llm.errors import StructuredOutputError
from hmap.core.tracing import get_logger

log = get_logger("hmap.llm.structured")

T = TypeVar("T", bound=BaseModel)
RawCall = Callable[[list[Message]], Awaitable[LLMResponse]]

MAX_REPAIRS = 2
REPAIR_PROMPT = (
    "Your previous reply was not valid JSON for the required schema.\n"
    "Validation error:\n{error}\n\n"
    "Reply again with ONLY the corrected JSON object that matches the schema. No prose, no code fences."
)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> str:
    """Best-effort: drop ``<think>`` blocks and code fences, then trim to the outermost JSON object/array."""
    cleaned = _THINK.sub("", text).strip()
    if m := _FENCE.search(cleaned):
        cleaned = m.group(1).strip()
    if cleaned and cleaned[0] not in "{[":
        starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
        if starts:
            start = min(starts)
            end = max(cleaned.rfind("}"), cleaned.rfind("]"))
            if end > start:
                cleaned = cleaned[start:end + 1]
    return cleaned


def validate_output(schema: type[T], text: str) -> T:
    """Raise ``ValidationError`` (invalid JSON included) or return the instance."""
    return schema.model_validate_json(extract_json(text))


class _Recursive(Exception):
    pass


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline local ``#/$defs/...`` references so small models' grammars get a flat schema. Recursive schemas are
    returned unchanged."""
    defs = schema.get("$defs")
    if not isinstance(defs, dict) or not defs:
        return schema

    def resolve(node: Any, stack: frozenset[str]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name in stack or name not in defs:
                    raise _Recursive(name)
                target = resolve(defs[name], stack | {name})
                extra = {k: resolve(v, stack) for k, v in node.items() if k != "$ref"}
                return {**target, **extra}
            return {k: resolve(v, stack) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v, stack) for v in node]
        return node

    try:
        out: dict[str, Any] = resolve(schema, frozenset())
    except _Recursive:
        return schema
    return out


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _sum_usage(total: LLMUsage | None, usage: LLMUsage) -> LLMUsage:
    if total is None:
        return usage
    return usage.model_copy(update={
        "input_tokens": total.input_tokens + usage.input_tokens,
        "output_tokens": total.output_tokens + usage.output_tokens,
        "latency_s": round(total.latency_s + usage.latency_s, 4),
        "cached": total.cached and usage.cached,
    })


async def generate_structured(call: RawCall, messages: list[Message], schema: type[T], *,
                              max_repairs: int = MAX_REPAIRS) -> LLMResponse:
    """Run ``call`` until its text validates against ``schema`` (1 + ``max_repairs`` attempts). Returns the last
    response with ``parsed`` set and usage summed over attempts; raises :class:`StructuredOutputError` otherwise."""
    attempt_msgs = list(messages)
    total: LLMUsage | None = None
    last_error = ""
    last_text = ""
    for attempt in range(max_repairs + 1):
        resp = await call(attempt_msgs)
        total = _sum_usage(total, resp.usage)
        try:
            parsed = validate_output(schema, resp.text)
        except ValidationError as exc:
            last_error = _short(str(exc), 1500)
            last_text = resp.text
            log.info("llm.structured.invalid", schema=schema.__name__, attempt=attempt, errors=exc.error_count())
            attempt_msgs = [*attempt_msgs, Message(role="assistant", content=_short(resp.text, 4000)),
                            Message(role="user", content=REPAIR_PROMPT.format(error=last_error))]
            continue
        return LLMResponse(text=resp.text, parsed=parsed, usage=total)
    raise StructuredOutputError(
        f"model output did not match {schema.__name__} after {max_repairs + 1} attempts: {last_error}",
        details={"schema": schema.__name__, "attempts": max_repairs + 1, "last_text": _short(last_text, 500)})

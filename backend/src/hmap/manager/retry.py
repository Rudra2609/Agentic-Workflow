"""Retry policy (research §23, §25, §26): what to do with a failed execution."""

import random
from dataclasses import dataclass
from enum import StrEnum

from hmap.core.errors import ErrorCode, is_retryable
from hmap.manager.config import ManagerConfig

# Codes that must never be retried blindly, whatever the agent claims (new input / revision / human needed).
NEVER_RETRY: frozenset[ErrorCode] = frozenset({
    ErrorCode.INVALID_MESSAGE, ErrorCode.INVALID_TASK, ErrorCode.SCHEMA_UNSUPPORTED,
    ErrorCode.AUTHENTICATION, ErrorCode.AUTHORIZATION, ErrorCode.ARTIFACT_CONFLICT,
    ErrorCode.ARTIFACT_INTEGRITY, ErrorCode.WRONG_RESULT, ErrorCode.CANCELLED,
})
# Codes that mean "cannot proceed until something is supplied" -> BLOCKED, not FAILED (research §25).
BLOCKING: frozenset[ErrorCode] = frozenset({ErrorCode.MISSING_CONTEXT, ErrorCode.DEPENDENCY})


class FailureAction(StrEnum):
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"
    FAIL = "fail"
    BLOCK = "block"


@dataclass(frozen=True)
class RetryDecision:
    action: FailureAction
    delay_s: float = 0.0


def to_code(code: ErrorCode | str) -> ErrorCode:
    try:
        return ErrorCode(code)
    except ValueError:
        return ErrorCode.INTERNAL_AGENT


def should_retry(code: ErrorCode | str, agent_says_retryable: bool | None = None) -> bool:
    """Taxonomy first; an agent may additionally flag e.g. INTERNAL_AGENT as retryable, never a NEVER_RETRY code."""
    c = to_code(code)
    if c in NEVER_RETRY or c in BLOCKING:
        return False
    if agent_says_retryable is None:
        return is_retryable(c)
    return agent_says_retryable


def backoff_delay(retry_index: int, config: ManagerConfig, rng: random.Random,
                  requested_s: float | None = None) -> float:
    """Delay before retry number ``retry_index`` (0-based): configured step + bounded jitter; honours a larger
    requested delay (``Retry-After`` / ``retry.request``)."""
    delays = config.retry_delays_s
    base = delays[min(retry_index, len(delays) - 1)]
    delay = base + rng.uniform(0.0, base * config.retry_jitter)
    return max(delay, requested_s or 0.0)


def decide(code: ErrorCode | str, *, retries_used: int, config: ManagerConfig, rng: random.Random,
           agent_says_retryable: bool | None = None, requested_delay_s: float | None = None) -> RetryDecision:
    c = to_code(code)
    if c in BLOCKING:
        return RetryDecision(FailureAction.BLOCK)
    if not should_retry(c, agent_says_retryable):
        return RetryDecision(FailureAction.FAIL)
    if retries_used >= config.max_retries:
        return RetryDecision(FailureAction.DEAD_LETTER)
    return RetryDecision(FailureAction.RETRY, backoff_delay(retries_used, config, rng, requested_delay_s))

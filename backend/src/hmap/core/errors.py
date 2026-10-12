"""Error taxonomy (research §25) and the retry classifier (§23)."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    INVALID_TASK = "INVALID_TASK"
    SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    DEPENDENCY = "DEPENDENCY"
    TOOL_TRANSIENT = "TOOL_TRANSIENT"
    MODEL_TRANSIENT = "MODEL_TRANSIENT"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    ARTIFACT_CONFLICT = "ARTIFACT_CONFLICT"
    ARTIFACT_INTEGRITY = "ARTIFACT_INTEGRITY"
    WRONG_RESULT = "WRONG_RESULT"
    CANCELLED = "CANCELLED"
    INTERNAL_AGENT = "INTERNAL_AGENT"


# Transient, classified faults that may be retried with backoff (§23). Everything else needs new input,
# a revision, or a human — never a blind retry.
RETRYABLE: frozenset[ErrorCode] = frozenset({
    ErrorCode.AGENT_UNAVAILABLE,
    ErrorCode.NETWORK,
    ErrorCode.TIMEOUT,
    ErrorCode.TOOL_TRANSIENT,
    ErrorCode.MODEL_TRANSIENT,
    ErrorCode.RESOURCE_EXHAUSTED,
})


def is_retryable(code: ErrorCode | str) -> bool:
    try:
        return ErrorCode(code) in RETRYABLE
    except ValueError:
        return False


class HmapError(Exception):
    """Base error carrying a taxonomy code; ``retryable`` defaults from the code."""

    code: ErrorCode = ErrorCode.INTERNAL_AGENT

    def __init__(self, message: str, *, code: ErrorCode | None = None, retryable: bool | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.retryable = is_retryable(self.code) if retryable is None else retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error_code": self.code.value, "message": self.message, "retryable": self.retryable,
                "details": self.details}


class InvalidMessage(HmapError):
    code = ErrorCode.INVALID_MESSAGE


class SchemaUnsupported(HmapError):
    code = ErrorCode.SCHEMA_UNSUPPORTED


class ArtifactIntegrityError(HmapError):
    code = ErrorCode.ARTIFACT_INTEGRITY


class ArtifactConflict(HmapError):
    code = ErrorCode.ARTIFACT_CONFLICT


class TransientError(HmapError):
    code = ErrorCode.TOOL_TRANSIENT


class ModelTransientError(HmapError):
    code = ErrorCode.MODEL_TRANSIENT


class AuthorizationError(HmapError):
    code = ErrorCode.AUTHORIZATION


class Cancelled(HmapError):
    code = ErrorCode.CANCELLED


def classify(exc: BaseException) -> ErrorCode:
    """Map an arbitrary exception to the taxonomy so the retry scheduler can decide."""
    if isinstance(exc, HmapError):
        return exc.code
    if isinstance(exc, TimeoutError):
        return ErrorCode.TIMEOUT
    if isinstance(exc, ConnectionError | OSError):
        return ErrorCode.NETWORK
    if isinstance(exc, MemoryError):
        return ErrorCode.RESOURCE_EXHAUSTED
    name = type(exc).__name__
    if name == "ValidationError":  # pydantic / jsonschema
        return ErrorCode.INVALID_MESSAGE
    if name in {"CancelledError"}:
        return ErrorCode.CANCELLED
    return ErrorCode.INTERNAL_AGENT

"""The common message envelope (research §7) with typed payload validation and version checks."""

from collections.abc import Callable
from typing import Any

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from hmap.core.contracts.common import (
    SCHEMA_VERSION,
    AgentRef,
    Contract,
    NonEmptyStr,
    ensure_compatible,
    utcnow,
)
from hmap.core.contracts.messages import COMMAND_TYPES, PAYLOAD_MODELS
from hmap.core.errors import InvalidMessage
from hmap.core.ids import new_uuid
from hmap.core.tracing import current_traceparent, is_valid_traceparent

MAX_MESSAGE_BYTES = 256 * 1024  # files never travel in messages (research §15); payloads stay small


class Envelope(Contract):
    message_id: NonEmptyStr = Field(default_factory=new_uuid)
    message_type: NonEmptyStr
    schema_version: str = SCHEMA_VERSION
    occurred_at: AwareDatetime = Field(default_factory=utcnow)
    sender: AgentRef
    receiver: AgentRef | None = None
    correlation_id: NonEmptyStr
    traceparent: str | None = None
    task_id: str | None = None
    execution_id: str | None = None
    project_id: str | None = None
    sequence_number: int | None = Field(default=None, ge=1)
    payload: dict[str, Any]
    auth: str | None = Field(default=None, repr=False, description="sender's signature (Sprint 6, hmap.core.policy)")

    @model_validator(mode="after")
    def _check(self) -> "Envelope":
        ensure_compatible(self.schema_version)
        model = PAYLOAD_MODELS.get(self.message_type)
        if model is None:
            raise ValueError(f"unknown message_type {self.message_type!r}")
        model.model_validate(self.payload)  # raises if the payload does not match its schema
        if self.message_type in COMMAND_TYPES and self.receiver is None:
            raise ValueError(f"{self.message_type} is a command and needs a receiver")
        if self.traceparent is not None and not is_valid_traceparent(self.traceparent):
            raise ValueError("invalid traceparent")
        return self

    def typed_payload(self) -> Contract:
        return PAYLOAD_MODELS[self.message_type].model_validate(self.payload)


_SIGNER: Callable[["Envelope"], str] | None = None


def register_signer(signer: Callable[["Envelope"], str] | None) -> None:
    """Sprint 6 (Member 6): ``hmap.core.policy.install`` registers the process's signer; every envelope built by
    :func:`make_envelope` is then signed (``auth``)."""
    global _SIGNER
    _SIGNER = signer


def make_envelope(payload: Contract, *, sender: str, correlation_id: str, receiver: str | None = None,
                  task_id: str | None = None, execution_id: str | None = None, project_id: str | None = None,
                  traceparent: str | None = None, sequence_number: int | None = None) -> Envelope:
    """Build a validated envelope from a payload model; the message_type is derived from the payload class."""
    message_type = next((t for t, m in PAYLOAD_MODELS.items() if isinstance(payload, m)), None)
    if message_type is None:
        raise InvalidMessage(f"{type(payload).__name__} is not a message payload")
    env = Envelope(
        message_type=message_type,
        sender=AgentRef(agent_id=sender),
        receiver=AgentRef(agent_id=receiver) if receiver else None,
        correlation_id=correlation_id,
        traceparent=traceparent or current_traceparent(),
        task_id=task_id,
        execution_id=execution_id or getattr(payload, "execution_id", None),
        project_id=project_id,
        sequence_number=sequence_number,
        payload=payload.model_dump(mode="json", exclude_none=True),
    )
    if _SIGNER is not None:
        env.auth = _SIGNER(env)
    return env


def parse_envelope(raw: bytes | str | dict[str, Any]) -> tuple[Envelope, Contract]:
    """Validate an incoming message. Raises InvalidMessage / SchemaUnsupported — never a raw ValidationError."""
    if isinstance(raw, bytes | str) and len(raw) > MAX_MESSAGE_BYTES:
        raise InvalidMessage(f"message larger than {MAX_MESSAGE_BYTES} bytes")
    try:
        env = Envelope.model_validate_json(raw) if isinstance(raw, bytes | str) else Envelope.model_validate(raw)
    except ValidationError as exc:  # SchemaUnsupported is not a ValueError, so pydantic lets it propagate as-is
        raise InvalidMessage(str(exc)) from exc
    return env, env.typed_payload()

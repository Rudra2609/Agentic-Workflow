"""Shared building blocks for every contract.

Versioning policy (research §28): ``schema_version`` is ``major.minor``. Within one major version new fields are
optional and **unknown fields are ignored**, so an older consumer keeps working when a producer adds a field.
A breaking change needs a new major version and an adapter. Contracts are additive-only (doc 01 §4).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from hmap.core.errors import SchemaUnsupported

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ("1.0",)

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    """Base class of all contracts: unknown fields ignored (forward-compatible), enums serialised as values."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, validate_assignment=True)


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class AgentRef(Contract):
    agent_id: NonEmptyStr


class ContextRef(Contract):
    """Pinned immutable context snapshot ``CTX-42@3`` (research §14)."""

    context_id: NonEmptyStr
    version: int = Field(ge=1)


class ArtifactRef(Contract):
    """Immutable, content-addressed artifact reference (research §15). A correction is a new version."""

    artifact_id: NonEmptyStr
    artifact_type: NonEmptyStr
    version: int = Field(ge=1)
    uri: NonEmptyStr
    sha256: Sha256Hex
    media_type: NonEmptyStr
    size_bytes: int = Field(ge=0)
    created_by: NonEmptyStr
    created_at: AwareDatetime
    access_scope: NonEmptyStr
    supersedes: int | None = Field(default=None, ge=1, description="previous version this one replaces")


# ------------------------------------------------------------------ version negotiation


def parse_version(version: str) -> tuple[int, int]:
    try:
        major, minor = version.split(".")
        return int(major), int(minor)
    except ValueError as exc:
        raise SchemaUnsupported(f"malformed schema_version {version!r}") from exc


def is_compatible(version: str, supported: tuple[str, ...] = SUPPORTED_SCHEMA_VERSIONS) -> bool:
    """Same major as something we support. A newer minor is fine: its extra fields are ignored."""
    major, _ = parse_version(version)
    return any(parse_version(s)[0] == major for s in supported)


def ensure_compatible(version: str) -> None:
    if not is_compatible(version):
        raise SchemaUnsupported(f"schema_version {version} not supported (supported: {SUPPORTED_SCHEMA_VERSIONS})")


def negotiate(ours: tuple[str, ...] | list[str], theirs: tuple[str, ...] | list[str]) -> str | None:
    """Highest version both sides support (manager vs agent registration), or None -> SCHEMA_UNSUPPORTED."""
    common = set(ours) & set(theirs)
    return max(common, key=parse_version) if common else None

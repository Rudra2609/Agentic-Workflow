"""Types of the models plug-in (Sprint 11). The contracts ``ModelSpec`` / ``RouteDecision`` / ``BenchmarkResult``
(``core/contracts/domain.py``) are the shared shapes; the rows here add what only this plug-in needs (digest,
source, pin, outcome) without changing a contract."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from hmap.core.contracts.domain import BenchmarkResult, ModelSpec, RouteDecision

Backend = Literal["ollama", "llamacpp", "mlx", "cloud"]
CHAT_ROLES = ("reasoner", "coder", "judge", "fast", "classify")
# heavier first is NOT the order: interactive work first, batch work last (scheduler priority, plan D4)
ROLE_PRIORITY = {"fast": 0, "classify": 0, "vision": 1, "reasoner": 1, "judge": 1, "coder": 2}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def decision_id() -> str:
    return f"rd-{uuid.uuid4().hex[:12]}"


class ModelRow(BaseModel):
    """A registry row: the contract plus where it came from."""

    spec: ModelSpec
    digest: str | None = None
    source: str = "snapshot"                 # ollama / cloud / mlx / llamacpp / snapshot
    pinned: bool = False
    resident_gb: float | None = None         # loaded right now (Ollama /api/ps)
    last_seen: str = Field(default_factory=now_iso)
    details: dict[str, Any] = Field(default_factory=dict)   # architecture keys (GGUF header), family, sizes


class RouteRecord(BaseModel):
    """One logged decision (no prompt, no answer: role, plug-in, model, reason, outcome only; plan Q10)."""

    id: str = Field(default_factory=decision_id)
    at: str = Field(default_factory=now_iso)
    decision: RouteDecision
    plugin: str
    est_tokens: int = 0
    chain: list[str] = Field(default_factory=list)     # what will be tried, in order ("groq:x", "ollama:qwen3.5:9b")
    rule: str = ""                                     # which rule decided (override / rules / table / default)
    answered_by: str | None = None                     # provider:model that answered
    ok: bool | None = None
    latency_s: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    rate_limited: int = 0
    error: str = ""


class BenchRow(BaseModel):
    """A ``BenchmarkResult`` plus how it was measured."""

    result: BenchmarkResult
    set_name: str
    n: int = 0
    run_id: str = ""
    digest: str | None = None
    seconds: float | None = None
    notes: str = ""
    at: str = Field(default_factory=now_iso)


__all__ = ["CHAT_ROLES", "ROLE_PRIORITY", "Backend", "BenchRow", "ModelRow", "ModelSpec", "RouteRecord",
           "decision_id", "now_iso"]

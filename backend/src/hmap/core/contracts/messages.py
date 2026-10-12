"""Payloads of the 15 message types (research §8). The envelope is in envelope.py."""

from typing import Any, Literal

from pydantic import AwareDatetime, Field

from hmap.core.contracts.capabilities import CapabilityDescriptor
from hmap.core.contracts.common import ArtifactRef, ContextRef, Contract, NonEmptyStr, Priority
from hmap.core.contracts.states import AgentState
from hmap.core.errors import ErrorCode


class TaskAssign(Contract):
    task_id: NonEmptyStr
    execution_id: NonEmptyStr
    capability: NonEmptyStr = Field(description="capability the selected agent must serve")
    objective: NonEmptyStr
    acceptance_criteria: list[str]
    context_refs: list[ContextRef]
    project_id: str | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list, description="inputs, e.g. uploaded documents")
    inputs: dict[str, Any] = Field(default_factory=dict, description="small structured inputs (ids, flags)")
    dependencies: list[str] = Field(default_factory=list)
    priority: Priority = Priority.NORMAL
    deadline: AwareDatetime | None = None
    refine: bool = False
    cloud_ok: bool = Field(default=True, description="false: a local-only project; the agent's LLM calls never use a "
                                                     "cloud model (the runtime enforces it, doc 02 §2.5)")


class TaskAck(Contract):
    execution_id: NonEmptyStr
    decision: Literal["accepted", "rejected"]
    reason: str | None = None
    available_slots: int | None = Field(default=None, ge=0)


class TaskStarted(Contract):
    execution_id: NonEmptyStr
    estimated_finish: AwareDatetime | None = None


class TaskProgress(Contract):
    execution_id: NonEmptyStr
    percent: int = Field(ge=0, le=100)
    summary: str
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)


class TaskResult(Contract):
    execution_id: NonEmptyStr
    outcome: Literal["success", "partial", "failure"]
    artifact_refs: list[ArtifactRef] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    summary: str | None = None


class Feedback(Contract):
    target_execution_id: NonEmptyStr
    decision: Literal["approve", "revise", "reject"]
    findings: list[str] = Field(default_factory=list)
    severity: Literal["info", "warning", "error"] | None = None


class RevisionRequest(Contract):
    new_execution_id: NonEmptyStr
    target_execution_id: NonEmptyStr
    required_changes: list[NonEmptyStr] = Field(min_length=1)
    context_refs: list[ContextRef] = Field(default_factory=list)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list, description="e.g. TestReport / ReviewReport")


class ContextRequest(Contract):
    execution_id: NonEmptyStr
    question: NonEmptyStr
    selectors: list[str] = Field(default_factory=list)


class ErrorPayload(Contract):
    execution_id: NonEmptyStr
    error_code: ErrorCode
    message: str
    retryable: bool
    diagnostics_ref: str | None = None


class RetryRequest(Contract):
    execution_id: NonEmptyStr
    reason: NonEmptyStr
    requested_delay_seconds: int | None = Field(default=None, ge=0)


class TaskCancel(Contract):
    task_id: NonEmptyStr
    reason: NonEmptyStr
    execution_id: str | None = None
    grace_deadline: AwareDatetime | None = None


class TaskCompleted(Contract):
    execution_id: NonEmptyStr
    final_status: Literal["completed", "failed", "cancelled"]
    result_ref: str | None = None


class AgentHeartbeat(Contract):
    agent_id: NonEmptyStr
    state: Literal[AgentState.AVAILABLE, AgentState.BUSY, AgentState.DRAINING, AgentState.RECOVERING]
    observed_at: AwareDatetime
    available_slots: int | None = Field(default=None, ge=0)
    current_execution_ids: list[str] = Field(default_factory=list)


class AgentRegister(Contract):
    agent_id: NonEmptyStr
    endpoint: NonEmptyStr = Field(description="queue name or URL the agent consumes from")
    capabilities: list[CapabilityDescriptor] = Field(min_length=1)
    protocol_versions: list[NonEmptyStr] = Field(min_length=1)
    max_slots: int = Field(default=1, ge=1)
    build_version: str | None = None
    model: str | None = None
    plugin: str | None = None
    is_stub: bool = False
    token: str | None = Field(default=None, repr=False, description="per-agent service token (Sprint 6)")


class AgentDeregister(Contract):
    agent_id: NonEmptyStr
    reason: NonEmptyStr
    drain_deadline: AwareDatetime | None = None


# message_type -> payload model. Order follows the research table.
PAYLOAD_MODELS: dict[str, type[Contract]] = {
    "task.assign": TaskAssign,
    "task.ack": TaskAck,
    "task.started": TaskStarted,
    "task.progress": TaskProgress,
    "task.result": TaskResult,
    "feedback": Feedback,
    "revision.request": RevisionRequest,
    "context.request": ContextRequest,
    "error": ErrorPayload,
    "retry.request": RetryRequest,
    "task.cancel": TaskCancel,
    "task.completed": TaskCompleted,
    "agent.heartbeat": AgentHeartbeat,
    "agent.register": AgentRegister,
    "agent.deregister": AgentDeregister,
}

# Commands ask a specific agent to act and therefore need a receiver (research §7); the rest are reports/events.
COMMAND_TYPES: frozenset[str] = frozenset({"task.assign", "revision.request", "task.cancel"})

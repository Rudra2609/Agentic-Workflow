"""Domain events (research §10): facts written to the outbox in the same transaction as the state change.

Event types are dotted lower-case strings so they double as RabbitMQ topic routing keys (``task.completed``).
Plug-ins may publish their own event types (e.g. ``refine.iteration``) as long as they follow the same pattern.
"""

from enum import StrEnum
from typing import Annotated, Any

from pydantic import AwareDatetime, Field, StringConstraints

from hmap.core.contracts.common import SCHEMA_VERSION, Contract, NonEmptyStr, ensure_compatible, utcnow
from hmap.core.ids import new_uuid

EventTypeName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")]


class EventType(StrEnum):
    # task / execution lifecycle (research §10)
    TASK_CREATED = "task.created"
    TASK_READY = "task.ready"
    TASK_ASSIGNED = "task.assigned"
    TASK_ACCEPTED = "task.accepted"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_RESULT_SUBMITTED = "task.result_submitted"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRYING = "task.retrying"
    TASK_BLOCKED = "task.blocked"
    TASK_CANCELLED = "task.cancelled"
    TASK_DEAD_LETTERED = "task.dead_lettered"
    TASK_REPLAYED = "task.replayed"                     # an operator replayed a dead letter (Sprint 4)
    REVIEW_REQUESTED = "review.requested"
    REVISION_REQUESTED = "revision.requested"
    # agents / registry
    AGENT_REGISTERED = "agent.registered"
    AGENT_OFFLINE = "agent.offline"
    AGENT_RECOVERED = "agent.recovered"
    # artifacts / context
    ARTIFACT_CREATED = "artifact.created"
    CONTEXT_UPDATED = "context.updated"
    # project pipeline + human gate
    PROJECT_CREATED = "project.created"
    DOCUMENT_UPLOADED = "document.uploaded"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    PROJECT_PLANNING = "project.planning"
    PROJECT_EXECUTING = "project.executing"
    PROJECT_COMPLETED = "project.completed"
    PROJECT_FAILED = "project.failed"
    # subsystem hand-offs named in the sprint files
    REQUIREMENTS_READY = "project.requirements_ready"  # M2 -> M3
    PLAN_APPROVED = "plan.approved"                     # M3 -> Manager
    RESEARCH_COMPLETED = "research.completed"           # M5 -> M6
    VERIFICATION_COMPLETED = "verification.completed"   # M6 -> Manager/M10
    CODE_COMPLETED = "code.completed"                   # M7 -> M8
    TEST_COMPLETED = "test.completed"                   # M8 -> M7/M10
    DOCS_COMPLETED = "docs.completed"                   # M9 -> M10
    REVIEW_COMPLETED = "review.completed"               # M10 -> Manager
    REFINE_ITERATION = "refine.iteration"               # M4
    REFINE_STOPPED = "refine.stopped"                   # M4


class DomainEvent(Contract):
    event_id: NonEmptyStr = Field(default_factory=new_uuid)
    event_type: EventTypeName
    aggregate_id: NonEmptyStr = Field(description="task_id, project_id or agent_id the event is about")
    aggregate_version: int = Field(default=0, ge=0, description="state_version after the change (ordering, §12)")
    occurred_at: AwareDatetime = Field(default_factory=utcnow)
    schema_version: str = SCHEMA_VERSION
    project_id: str | None = None
    correlation_id: str | None = None
    traceparent: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        ensure_compatible(self.schema_version)

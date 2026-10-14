"""Manager-owned persistent records (research §34). Mirrors the Postgres tables of item 1.5; the in-memory store
keeps copies of these models, so callers can never mutate stored state without going through a transaction."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hmap.core.contracts import ArtifactRef, ContextRef, ExecutionStatus, Priority, ProjectState, TaskState


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class RunRecord(Record):
    """One pass of the pipeline over a project (an upload or a typed goal starts one). Earlier runs and their tasks
    are kept: a new run never overwrites history."""

    number: int
    started_at: datetime
    finished_at: datetime | None = None
    outcome: ProjectState | None = None      # COMPLETED / FAILED / CANCELLED once settled
    goal: str | None = None                  # the typed request, if the run started from text
    documents: list[str] = Field(default_factory=list, description="uploaded file names (folder/name)")
    document_ids: list[str] = Field(default_factory=list, description="artifact id of each of `documents`, same order")


class ProjectRecord(Record):
    project_id: str
    name: str
    owner_id: str | None = Field(default=None, description="user who owns the project (the API's security boundary)")
    description: str | None = None
    state: ProjectState = ProjectState.CREATED
    state_version: int = 1
    created_at: datetime
    updated_at: datetime
    graph_version: int | None = None
    plan_task_map: dict[str, str] = Field(default_factory=dict, description="plan task id -> real task id")
    auto_approve: bool = Field(default=False, description="plan is shown, then approved automatically (no human gate)")
    cloud_ok: bool = Field(default=True, description="false keeps the project on this computer: its steps never use "
                                                     "a cloud model, even with team keys configured (doc 02 §2.5)")
    refine: bool = Field(default=False, description="check and improve each result before it is reported (Sprint 4: "
                                                     "copied into TaskAssign.refine; slower, more model calls)")
    stopped_reason: str | None = Field(default=None, description="set when a human pressed Stop")
    runs: list[RunRecord] = Field(default_factory=list)
    archived: bool = False
    deleted_at: datetime | None = Field(default=None, description="soft-deleted: invisible to every API call")

    @property
    def current_run(self) -> int:
        return len(self.runs) or 1


class TaskRecord(Record):
    task_id: str
    project_id: str
    capability: str
    objective: str
    title: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    context_refs: list[ContextRef] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    plan_task_id: str | None = None
    run: int = 1                          # RunRecord.number this task belongs to
    priority: Priority = Priority.NORMAL
    needs_approval: bool = False          # graph task waiting for the human plan-approval gate
    state: TaskState = TaskState.CREATED
    state_version: int = 1
    active_execution_id: str | None = None
    attempts: int = 0                     # executions created so far (= highest attempt number)
    retries: int = 0                      # retry budget consumed (retryable failures)
    rejections: int = 0                   # task.ack rejected since the last retry
    rejected_by: list[str] = Field(default_factory=list)
    retry_at: datetime | None = None
    last_error: dict[str, Any] | None = None
    blocked_by: list[str] = Field(default_factory=list)
    replaced: bool = Field(default=False, description="graph task dropped by a replan (Sprint 3): kept as history, "
                                                     "ignored by the executor and the project outcome")
    replays: int = Field(default=0, description="times an operator replayed it from DEAD_LETTERED (Sprint 4)")
    created_at: datetime
    updated_at: datetime


class ExecutionRecord(Record):
    execution_id: str
    task_id: str
    attempt: int
    status: ExecutionStatus = ExecutionStatus.PENDING
    agent_id: str | None = None
    lease_until: datetime | None = None   # ack deadline while PENDING; agent lease (from heartbeats) afterwards
    orphaned_at: datetime | None = None   # set when the agent went OFFLINE/deregistered (grace period starts)
    outcome: str | None = None
    result_refs: list[ArtifactRef] = Field(default_factory=list)
    result_summary: str | None = None
    error: dict[str, Any] | None = None
    superseded_by: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list, description="late / stale reports, kept (§17)")
    created_at: datetime
    updated_at: datetime


class ApprovalRecord(Record):
    approval_id: str
    project_id: str
    graph_version: int | None = None
    status: Literal["pending", "approved", "rejected"] = "pending"
    comment: str | None = None
    requested_at: datetime
    decided_at: datetime | None = None

"""State enums shared by Manager, registry, API and UI. Transition rules live in hmap.manager (Member 1)."""

from enum import StrEnum


class TaskState(StrEnum):
    """Logical task lifecycle (research §9) + NEEDS_REVISION (review loop, Sprint 10)."""

    CREATED = "CREATED"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DEAD_LETTERED = "DEAD_LETTERED"
    FAILED = "FAILED"
    NEEDS_REVISION = "NEEDS_REVISION"


TERMINAL_TASK_STATES: frozenset[TaskState] = frozenset(
    {TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED, TaskState.DEAD_LETTERED}
)


class ExecutionStatus(StrEnum):
    """One attempt at a task (research §18: a retry is a new execution; the old one is superseded)."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    DEAD_LETTERED = "DEAD_LETTERED"


class AgentState(StrEnum):
    """Advertised agent lifecycle (research §16, §21)."""

    STARTING = "STARTING"
    REGISTERING = "REGISTERING"
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    OFFLINE = "OFFLINE"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"


class ProjectState(StrEnum):
    """Whole-project pipeline, including the human plan-approval gate (Sprint 1 item 1.13, Sprint 3)."""

    CREATED = "CREATED"
    INGESTING = "INGESTING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

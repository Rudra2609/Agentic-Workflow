"""Task store (research §17, §24, §34): projects, tasks, executions, approvals + the outbox, written together.

Every write goes through a unit of work::

    async with store.transaction() as tx:
        task = await tx.get_task(task_id)
        task = await tx.update_task(task.model_copy(update={...}), expected_version=task.state_version)
        await tx.add_event(event)          # outbox row, committed atomically with the update

``update_*`` are compare-and-swap on ``state_version`` (``UPDATE ... WHERE state_version = ?``) and bump it by one;
a mismatch raises :class:`ConcurrencyConflict`. ``(task_id, attempt)`` is unique (:class:`UniqueViolation`).
Leaving the ``async with`` normally commits; an exception discards every staged write and outbox row.

``InMemoryTaskStore`` serialises transactions with one ``asyncio.Lock`` and stages writes until commit.
A Postgres implementation (Phase B) maps ``transaction()`` to a DB transaction and the outbox to a table in it.
"""

import asyncio
from collections.abc import AsyncIterator, Collection
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol, TypeVar

from hmap.core.bus.stores import OutboxStore
from hmap.core.contracts import DomainEvent, Envelope, ExecutionStatus, TaskState
from hmap.manager.records import ApprovalRecord, ExecutionRecord, ProjectRecord, Record, TaskRecord


class StoreError(Exception):
    """Base class of store integrity errors."""


class ConcurrencyConflict(StoreError):
    """CAS failed: the record changed since it was read (another writer won)."""


class UniqueViolation(StoreError):
    """A unique key (``task_id``, ``execution_id``, ``(task_id, attempt)`` ...) already exists."""


class RecordNotFound(StoreError, KeyError):
    """Update of a record that does not exist."""


class TaskStoreReader(Protocol):
    async def get_project(self, project_id: str) -> ProjectRecord | None: ...
    async def list_projects(self, *, owner_id: str | None = None) -> list[ProjectRecord]: ...
    async def get_task(self, task_id: str) -> TaskRecord | None: ...
    async def list_tasks(self, *, project_id: str | None = None,
                         states: Collection[TaskState] | None = None) -> list[TaskRecord]: ...
    async def get_execution(self, execution_id: str) -> ExecutionRecord | None: ...
    async def list_executions(self, *, task_id: str | None = None, agent_id: str | None = None,
                              statuses: Collection[ExecutionStatus] | None = None) -> list[ExecutionRecord]: ...
    async def list_approvals(self, *, project_id: str | None = None) -> list[ApprovalRecord]: ...


class TaskStoreTx(TaskStoreReader, Protocol):
    """One unit of work. Reads see this transaction's own staged writes."""

    async def insert_project(self, project: ProjectRecord) -> ProjectRecord: ...
    async def update_project(self, project: ProjectRecord, *, expected_version: int) -> ProjectRecord: ...
    async def insert_task(self, task: TaskRecord) -> TaskRecord: ...
    async def update_task(self, task: TaskRecord, *, expected_version: int) -> TaskRecord: ...
    async def insert_execution(self, execution: ExecutionRecord) -> ExecutionRecord: ...
    async def update_execution(self, execution: ExecutionRecord) -> ExecutionRecord: ...
    async def insert_approval(self, approval: ApprovalRecord) -> ApprovalRecord: ...
    async def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord: ...
    async def add_event(self, event: DomainEvent) -> None: ...
    async def add_command(self, capability: str, envelope: Envelope) -> None: ...


class TaskStore(TaskStoreReader, Protocol):
    """Reads outside a transaction return committed state."""

    def transaction(self) -> AbstractAsyncContextManager[TaskStoreTx]: ...


# ===================================================================================================== in-memory

R = TypeVar("R", bound=Record)


@dataclass
class _Tables:
    projects: dict[str, ProjectRecord]
    tasks: dict[str, TaskRecord]
    executions: dict[str, ExecutionRecord]
    approvals: dict[str, ApprovalRecord]


def _copy(rec: R) -> R:
    return rec.model_copy(deep=True)


class _Reads:
    """Read helpers over a table view (committed, or committed + staged)."""

    def _view(self) -> _Tables:
        raise NotImplementedError

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        p = self._view().projects.get(project_id)
        return _copy(p) if p else None

    async def list_projects(self, *, owner_id: str | None = None) -> list[ProjectRecord]:
        return sorted((_copy(p) for p in self._view().projects.values() if owner_id is None or p.owner_id == owner_id),
                      key=lambda p: (p.created_at, p.project_id))

    async def get_task(self, task_id: str) -> TaskRecord | None:
        t = self._view().tasks.get(task_id)
        return _copy(t) if t else None

    async def list_tasks(self, *, project_id: str | None = None,
                         states: Collection[TaskState] | None = None) -> list[TaskRecord]:
        out = [_copy(t) for t in self._view().tasks.values()
               if (project_id is None or t.project_id == project_id) and (states is None or t.state in states)]
        return sorted(out, key=lambda t: (t.created_at, t.task_id))

    async def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        e = self._view().executions.get(execution_id)
        return _copy(e) if e else None

    async def list_executions(self, *, task_id: str | None = None, agent_id: str | None = None,
                              statuses: Collection[ExecutionStatus] | None = None) -> list[ExecutionRecord]:
        out = [_copy(e) for e in self._view().executions.values()
               if (task_id is None or e.task_id == task_id) and (agent_id is None or e.agent_id == agent_id)
               and (statuses is None or e.status in statuses)]
        return sorted(out, key=lambda e: (e.task_id, e.attempt))

    async def list_approvals(self, *, project_id: str | None = None) -> list[ApprovalRecord]:
        out = [_copy(a) for a in self._view().approvals.values() if project_id is None or a.project_id == project_id]
        return sorted(out, key=lambda a: (a.requested_at, a.approval_id))


class _InMemoryTx(_Reads):
    def __init__(self, committed: _Tables) -> None:
        self._committed = committed
        # staged copies (copy-on-write); merged into ``committed`` on commit
        self._staged = _Tables({}, {}, {}, {})
        self.outbox_rows: list[tuple[str, DomainEvent | Envelope, str | None]] = []

    def _view(self) -> _Tables:
        c, s = self._committed, self._staged
        return _Tables({**c.projects, **s.projects}, {**c.tasks, **s.tasks},
                       {**c.executions, **s.executions}, {**c.approvals, **s.approvals})

    # --------------------------------------------------------------------------- writes

    @staticmethod
    def _cas(current: ProjectRecord | TaskRecord | None, key: str, expected_version: int) -> int:
        if current is None:
            raise RecordNotFound(key)
        if current.state_version != expected_version:
            raise ConcurrencyConflict(f"{key}: expected version {expected_version}, found {current.state_version}")
        return expected_version + 1

    async def insert_project(self, project: ProjectRecord) -> ProjectRecord:
        if project.project_id in self._view().projects:
            raise UniqueViolation(f"project {project.project_id} exists")
        self._staged.projects[project.project_id] = _copy(project)
        return _copy(project)

    async def update_project(self, project: ProjectRecord, *, expected_version: int) -> ProjectRecord:
        version = self._cas(self._view().projects.get(project.project_id), project.project_id, expected_version)
        new = project.model_copy(deep=True, update={"state_version": version})
        self._staged.projects[project.project_id] = new
        return _copy(new)

    async def insert_task(self, task: TaskRecord) -> TaskRecord:
        if task.task_id in self._view().tasks:
            raise UniqueViolation(f"task {task.task_id} exists")
        self._staged.tasks[task.task_id] = _copy(task)
        return _copy(task)

    async def update_task(self, task: TaskRecord, *, expected_version: int) -> TaskRecord:
        version = self._cas(self._view().tasks.get(task.task_id), task.task_id, expected_version)
        new = task.model_copy(deep=True, update={"state_version": version})
        self._staged.tasks[task.task_id] = new
        return _copy(new)

    async def insert_execution(self, execution: ExecutionRecord) -> ExecutionRecord:
        view = self._view().executions
        if execution.execution_id in view:
            raise UniqueViolation(f"execution {execution.execution_id} exists")
        if any(e.task_id == execution.task_id and e.attempt == execution.attempt for e in view.values()):
            raise UniqueViolation(f"(task_id, attempt) = ({execution.task_id}, {execution.attempt}) exists")
        self._staged.executions[execution.execution_id] = _copy(execution)
        return _copy(execution)

    async def update_execution(self, execution: ExecutionRecord) -> ExecutionRecord:
        current = self._view().executions.get(execution.execution_id)
        if current is None:
            raise RecordNotFound(execution.execution_id)
        if (current.task_id, current.attempt) != (execution.task_id, execution.attempt):
            raise UniqueViolation("execution task_id/attempt are immutable")
        self._staged.executions[execution.execution_id] = _copy(execution)
        return _copy(execution)

    async def insert_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        if approval.approval_id in self._view().approvals:
            raise UniqueViolation(f"approval {approval.approval_id} exists")
        self._staged.approvals[approval.approval_id] = _copy(approval)
        return _copy(approval)

    async def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        if approval.approval_id not in self._view().approvals:
            raise RecordNotFound(approval.approval_id)
        self._staged.approvals[approval.approval_id] = _copy(approval)
        return _copy(approval)

    async def add_event(self, event: DomainEvent) -> None:
        self.outbox_rows.append(("event", event, None))

    async def add_command(self, capability: str, envelope: Envelope) -> None:
        self.outbox_rows.append(("command", envelope, capability))

    def commit(self) -> None:
        c, s = self._committed, self._staged
        c.projects.update(s.projects)
        c.tasks.update(s.tasks)
        c.executions.update(s.executions)
        c.approvals.update(s.approvals)


class InMemoryTaskStore(_Reads):
    """Phase-A store. One ``asyncio.Lock`` = one writer at a time; never hold it across agent work."""

    def __init__(self, outbox: OutboxStore) -> None:
        self.outbox = outbox
        self._tables = _Tables({}, {}, {}, {})
        self._lock = asyncio.Lock()

    def _view(self) -> _Tables:
        return self._tables

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[TaskStoreTx]:
        async with self._lock:
            tx = _InMemoryTx(self._tables)
            yield tx
            # Commit: outbox rows first (in-memory outbox add is not expected to fail); then the state.
            for kind, body, capability in tx.outbox_rows:
                await self.outbox.add(kind, body, capability)
            tx.commit()

    def transaction(self) -> AbstractAsyncContextManager[TaskStoreTx]:
        return self._transaction()

"""Postgres ``TaskStore`` (Sprint 1 items 1.5/1.8; research §17, §18, §22, §34). Same behaviour as
``InMemoryTaskStore``; the transactional-outbox guarantee comes from the database instead of a Python lock.

- ``transaction()`` is ONE database transaction (READ COMMITTED). Reads inside it see its own writes; reads on the
  store see committed state only. Leaving the block normally commits; an exception rolls everything back,
  including the outbox rows.
- ``update_project`` / ``update_task`` are compare-and-swap: ``UPDATE ... WHERE state_version = :expected``; zero
  rows -> :class:`ConcurrencyConflict` (or :class:`RecordNotFound` if the row does not exist). A concurrent writer
  that has updated the row but not committed yet makes the UPDATE wait, then re-check the predicate against the
  committed version, so exactly one of two racing transactions wins.
- Inserts run in a SAVEPOINT, so a :class:`UniqueViolation` leaves the transaction usable (as in memory).
- Deadlocks / serialization failures surface as :class:`ConcurrencyConflict` (the Manager nacks and redelivers).
- ``add_event`` / ``add_command`` stage outbox rows that are INSERTed as the last statements of the same
  transaction, under the outbox advisory lock (``hmap.core.bus.pg_stores``: seq order == commit order).
- Records are stored as typed columns (for filters/sorting) + the full model in ``data`` jsonb; reads rebuild a
  fresh (detached) pydantic model from ``data``. String ids sort with ``COLLATE "C"`` (= Python ordering).

Serialisation (two independent knobs):

- ``local_lock=True`` (default): this store object runs its transactions one at a time, in FIFO order, via an
  ``asyncio.Lock`` -- exactly ``InMemoryTaskStore``'s behaviour. The Manager depends on it: it consumes replies with
  prefetch 16, and without in-order processing a ``task.result`` can be handled before the ``task.ack`` /
  ``task.started`` of the same execution has committed; it is then classified as out-of-order evidence and the task
  never completes. Across processes (another store object / another Manager) only CAS protects the rows.
- ``serialize_writes=True`` (off by default): every transaction also takes one database advisory lock, i.e. a single
  writer at a time across all processes. Only needed if several Manager processes share one database.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Collection
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, TypeVar

import psycopg
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb

from hmap.core.bus.pg_stores import OutboxItem, PostgresOutboxStore, insert_outbox_rows, record_inbox
from hmap.core.bus.pg_stores import validate_outbox_row as _validate_outbox_row
from hmap.core.contracts import DomainEvent, Envelope, ExecutionStatus, TaskState
from hmap.db.database import Conn, Database
from hmap.manager.records import ApprovalRecord, ExecutionRecord, ProjectRecord, Record, TaskRecord
from hmap.manager.store import ConcurrencyConflict, RecordNotFound, TaskStoreTx, UniqueViolation

R = TypeVar("R", bound=Record)

WRITER_LOCK_KEY = 0x686D_6170_0003      # serialize_writes=True
_CONFLICT_SQLSTATES = frozenset({"40001", "40P01", "55P03"})   # serialization failure, deadlock, lock not available


def _is_conflict(exc: BaseException) -> bool:
    return isinstance(exc, psycopg.Error) and getattr(exc, "sqlstate", None) in _CONFLICT_SQLSTATES


def _values(states: Collection[Any]) -> list[str]:
    return [s.value if hasattr(s, "value") else str(s) for s in states]


# ------------------------------------------------------------------ record <-> row

def _project_cols(p: ProjectRecord) -> dict[str, Any]:
    return {"project_id": p.project_id, "name": p.name, "state": p.state.value, "state_version": p.state_version,
            "graph_version": p.graph_version, "created_at": p.created_at, "updated_at": p.updated_at,
            "owner_id": p.owner_id, "data": Jsonb(p.to_dict())}


def _task_cols(t: TaskRecord) -> dict[str, Any]:
    return {"task_id": t.task_id, "project_id": t.project_id, "capability": t.capability, "state": t.state.value,
            "state_version": t.state_version, "parent_task_id": t.parent_task_id, "plan_task_id": t.plan_task_id,
            "active_execution_id": t.active_execution_id, "priority": t.priority.value, "retry_at": t.retry_at,
            "created_at": t.created_at, "updated_at": t.updated_at, "data": Jsonb(t.to_dict())}


def _execution_cols(e: ExecutionRecord) -> dict[str, Any]:
    return {"execution_id": e.execution_id, "task_id": e.task_id, "attempt": e.attempt, "status": e.status.value,
            "agent_id": e.agent_id, "lease_until": e.lease_until, "created_at": e.created_at,
            "updated_at": e.updated_at, "data": Jsonb(e.to_dict())}


def _approval_cols(a: ApprovalRecord) -> dict[str, Any]:
    return {"approval_id": a.approval_id, "project_id": a.project_id, "graph_version": a.graph_version,
            "status": a.status, "requested_at": a.requested_at, "decided_at": a.decided_at,
            "data": Jsonb(a.to_dict())}


def _insert_sql(table: str, cols: dict[str, Any]) -> str:
    names = ", ".join(cols)
    params = ", ".join(f"%({c})s" for c in cols)
    return f"INSERT INTO {table} ({names}) VALUES ({params})"


def _update_sql(table: str, key: str, cols: dict[str, Any], *, cas: bool = False) -> str:
    sets = ", ".join(f"{c} = %({c})s" for c in cols if c != key)
    where = f"{key} = %({key})s" + (" AND state_version = %(expected_version)s" if cas else "")
    return f"UPDATE {table} SET {sets} WHERE {where}"


# ------------------------------------------------------------------ reads

class _Reads:
    """Read helpers; subclasses decide which connection runs the query."""

    async def _fetch(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _one(self, model: type[R], query: str, params: Any) -> R | None:
        rows = await self._fetch(query, params)
        return model.model_validate(rows[0]["data"]) if rows else None

    async def _many(self, model: type[R], query: str, params: Any = None) -> list[R]:
        return [model.model_validate(r["data"]) for r in await self._fetch(query, params)]

    async def get_project(self, project_id: str) -> ProjectRecord | None:
        return await self._one(ProjectRecord, "SELECT data FROM projects WHERE project_id = %s", (project_id,))

    async def list_projects(self, *, owner_id: str | None = None) -> list[ProjectRecord]:
        if owner_id is not None:
            return await self._many(ProjectRecord, 'SELECT data FROM projects WHERE owner_id = %s'
                                                   ' ORDER BY created_at, project_id COLLATE "C"', (owner_id,))
        return await self._many(ProjectRecord,
                                'SELECT data FROM projects ORDER BY created_at, project_id COLLATE "C"')

    async def get_task(self, task_id: str) -> TaskRecord | None:
        return await self._one(TaskRecord, "SELECT data FROM tasks WHERE task_id = %s", (task_id,))

    async def list_tasks(self, *, project_id: str | None = None,
                         states: Collection[TaskState] | None = None) -> list[TaskRecord]:
        where: list[str] = ["TRUE"]
        params: dict[str, Any] = {}
        if project_id is not None:
            where.append("project_id = %(project_id)s")
            params["project_id"] = project_id
        if states is not None:
            where.append("state = ANY(%(states)s)")
            params["states"] = _values(states)
        return await self._many(TaskRecord, f"SELECT data FROM tasks WHERE {' AND '.join(where)}"
                                            ' ORDER BY created_at, task_id COLLATE "C"', params)

    async def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        return await self._one(ExecutionRecord, "SELECT data FROM executions WHERE execution_id = %s",
                               (execution_id,))

    async def list_executions(self, *, task_id: str | None = None, agent_id: str | None = None,
                              statuses: Collection[ExecutionStatus] | None = None) -> list[ExecutionRecord]:
        where: list[str] = ["TRUE"]
        params: dict[str, Any] = {}
        if task_id is not None:
            where.append("task_id = %(task_id)s")
            params["task_id"] = task_id
        if agent_id is not None:
            where.append("agent_id = %(agent_id)s")
            params["agent_id"] = agent_id
        if statuses is not None:
            where.append("status = ANY(%(statuses)s)")
            params["statuses"] = _values(statuses)
        return await self._many(ExecutionRecord, f"SELECT data FROM executions WHERE {' AND '.join(where)}"
                                                 ' ORDER BY task_id COLLATE "C", attempt', params)

    async def list_approvals(self, *, project_id: str | None = None) -> list[ApprovalRecord]:
        if project_id is None:
            return await self._many(ApprovalRecord,
                                    'SELECT data FROM approvals ORDER BY requested_at, approval_id COLLATE "C"')
        return await self._many(ApprovalRecord, "SELECT data FROM approvals WHERE project_id = %s"
                                                ' ORDER BY requested_at, approval_id COLLATE "C"', (project_id,))


# ------------------------------------------------------------------ unit of work

class PostgresTx(_Reads):
    """``TaskStoreTx`` bound to one connection that is inside a transaction."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self.outbox_rows: list[OutboxItem] = []

    async def _fetch(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        cur = await self.conn.execute(query, params)
        return await cur.fetchall()

    async def _insert(self, table: str, cols: dict[str, Any], what: str) -> None:
        try:
            async with self.conn.transaction():          # SAVEPOINT: a failed insert keeps the tx usable
                await self.conn.execute(_insert_sql(table, cols), cols)
        except pg_errors.UniqueViolation as exc:
            raise UniqueViolation(f"{what} exists ({exc.diag.constraint_name})") from exc

    async def _cas(self, table: str, key: str, cols: dict[str, Any], expected_version: int) -> None:
        cur = await self.conn.execute(_update_sql(table, key, cols, cas=True),
                                      {**cols, "expected_version": expected_version})
        if cur.rowcount == 1:
            return
        rows = await self._fetch(f"SELECT state_version FROM {table} WHERE {key} = %s", (cols[key],))
        if not rows:
            raise RecordNotFound(cols[key])
        raise ConcurrencyConflict(
            f"{cols[key]}: expected version {expected_version}, found {rows[0]['state_version']}")

    # --------------------------------------------------------------------------- writes

    async def insert_project(self, project: ProjectRecord) -> ProjectRecord:
        await self._insert("projects", _project_cols(project), f"project {project.project_id}")
        return project.model_copy(deep=True)

    async def update_project(self, project: ProjectRecord, *, expected_version: int) -> ProjectRecord:
        new = project.model_copy(deep=True, update={"state_version": expected_version + 1})
        await self._cas("projects", "project_id", _project_cols(new), expected_version)
        return new.model_copy(deep=True)

    async def insert_task(self, task: TaskRecord) -> TaskRecord:
        await self._insert("tasks", _task_cols(task), f"task {task.task_id}")
        return task.model_copy(deep=True)

    async def update_task(self, task: TaskRecord, *, expected_version: int) -> TaskRecord:
        new = task.model_copy(deep=True, update={"state_version": expected_version + 1})
        await self._cas("tasks", "task_id", _task_cols(new), expected_version)
        return new.model_copy(deep=True)

    async def insert_execution(self, execution: ExecutionRecord) -> ExecutionRecord:
        await self._insert("executions", _execution_cols(execution),
                           f"execution {execution.execution_id} / (task_id, attempt) = "
                           f"({execution.task_id}, {execution.attempt})")
        return execution.model_copy(deep=True)

    async def update_execution(self, execution: ExecutionRecord) -> ExecutionRecord:
        rows = await self._fetch("SELECT task_id, attempt FROM executions WHERE execution_id = %s FOR UPDATE",
                                 (execution.execution_id,))
        if not rows:
            raise RecordNotFound(execution.execution_id)
        if (rows[0]["task_id"], rows[0]["attempt"]) != (execution.task_id, execution.attempt):
            raise UniqueViolation("execution task_id/attempt are immutable")
        cols = _execution_cols(execution)
        await self.conn.execute(_update_sql("executions", "execution_id", cols), cols)
        return execution.model_copy(deep=True)

    async def insert_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        await self._insert("approvals", _approval_cols(approval), f"approval {approval.approval_id}")
        return approval.model_copy(deep=True)

    async def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        cols = _approval_cols(approval)
        cur = await self.conn.execute(_update_sql("approvals", "approval_id", cols), cols)
        if cur.rowcount == 0:
            raise RecordNotFound(approval.approval_id)
        return approval.model_copy(deep=True)

    async def add_event(self, event: DomainEvent) -> None:
        _validate_outbox_row("event", event, None)
        self.outbox_rows.append(("event", event.model_copy(deep=True), None))

    async def add_command(self, capability: str, envelope: Envelope) -> None:
        _validate_outbox_row("command", envelope, capability)
        self.outbox_rows.append(("command", envelope.model_copy(deep=True), capability))

    # --------------------------------------------------------------------------- extras (not in the protocol)

    async def record_inbox(self, consumer_id: str, message_id: str) -> bool:
        """Inbox dedup key in THIS transaction (research §24): False = already processed (effect committed)."""
        return await record_inbox(self.conn, consumer_id, message_id)

    async def flush_outbox(self) -> list[int]:
        """Insert the staged outbox rows now (normally done right before COMMIT). Returns their seqs."""
        rows, self.outbox_rows = self.outbox_rows, []
        return await insert_outbox_rows(self.conn, rows)


class PostgresTaskStore(_Reads):
    """``TaskStore`` on Postgres. ``outbox`` is a :class:`PostgresOutboxStore` on the same database (the publisher
    drains it); the store writes outbox rows itself, inside each transaction."""

    def __init__(self, db: Database, *, local_lock: bool = True, serialize_writes: bool = False) -> None:
        self.db = db
        self.outbox = PostgresOutboxStore(db)
        self.local_lock = local_lock
        self.serialize_writes = serialize_writes
        self._lock = asyncio.Lock()

    async def _fetch(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        return await self.db.fetch(query, params)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[TaskStoreTx]:
        try:
            async with self._lock if self.local_lock else contextlib.nullcontext(), self.db.transaction() as conn:
                if self.serialize_writes:
                    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (WRITER_LOCK_KEY,))
                tx = PostgresTx(conn)
                yield tx
                await tx.flush_outbox()          # last statements before COMMIT (outbox lock held until commit)
        except psycopg.Error as exc:
            if _is_conflict(exc):
                raise ConcurrencyConflict(f"transaction aborted by a concurrent writer: {exc}") from exc
            raise

    def transaction(self) -> AbstractAsyncContextManager[TaskStoreTx]:
        return self._transaction()

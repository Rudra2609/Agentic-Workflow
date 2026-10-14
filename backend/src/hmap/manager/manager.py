"""The Manager (Sprint 1 item 1.13): owns task state, assigns work, consumes agent reports, retries, times out,
cancels and drives task graphs. Implements :class:`hmap.core.plugins.ManagerHandle`.

Data flow::

    API / hooks ──► Manager ──(unit of work: state + events + task.assign commands)──► TaskStore + Outbox
    outbox publisher ──► bus (hmap.cap.<capability>, hmap.events)
    agents ──(task.ack/started/progress/result, error, agent.*)──► bus.consume_replies ──► Manager

Rules (research §9, §12, §17, §18, §23, §26):

- Every state change is a CAS update + its DomainEvent written in ONE unit of work; ``aggregate_version`` is the
  task's new ``state_version``. Plug-in hooks run after commit; a failing hook is logged, never fatal.
- Only the task's *active* execution may move it. Reports from any other execution (superseded, timed out,
  cancelled, after a terminal state) are appended to that execution's ``evidence`` and change nothing.
- Retryable failures: ``RETRY_SCHEDULED`` with backoff + jitter, then a NEW execution (previous one ``SUPERSEDED``);
  budget exhausted -> ``DEAD_LETTERED``. Non-retryable -> ``FAILED``. ``MISSING_CONTEXT``/``DEPENDENCY`` ->
  ``BLOCKED``. Dependants of failed/dead-lettered/cancelled/blocked tasks become ``BLOCKED``.
- A delivery is acked only after its store update has committed.
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from hmap.core.bus.base import Bus, Delivery, Subscription
from hmap.core.bus.stores import InboxStore, OutboxStore
from hmap.core.contracts import (
    AgentDeregister,
    AgentHeartbeat,
    AgentRegister,
    ArtifactRef,
    Contract,
    DomainEvent,
    Envelope,
    ErrorPayload,
    EventType,
    ExecutionStatus,
    ProjectState,
    RetryRequest,
    TaskAck,
    TaskAssign,
    TaskGraph,
    TaskProgress,
    TaskResult,
    TaskStarted,
    TaskState,
    make_envelope,
    utcnow,
)
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.ids import new_execution_id, new_project_id, new_task_id, new_uuid
from hmap.core.plugins import Plugin, ProjectStopped
from hmap.manager.assignment import IN_FLIGHT_EXECUTIONS, agent_load, assignment_order, choose_agent
from hmap.manager.config import ManagerConfig
from hmap.manager.executor import GraphExecutor, NaiveTopologicalExecutor
from hmap.manager.hooks import HookDispatcher, resolve_strategy
from hmap.manager.records import ApprovalRecord, ExecutionRecord, ProjectRecord, RunRecord, TaskRecord
from hmap.manager.retry import FailureAction, decide
from hmap.manager.store import StoreError, TaskStore, TaskStoreTx
from hmap.manager.transitions import IN_FLIGHT_STATES, STATE_EVENT, check_transition, classify, is_terminal
from hmap.manager.watchdog import ack_timed_out, scan_orphans
from hmap.obs import metrics as obs_metrics
from hmap.obs import telemetry
from hmap.services.artifact.base import ArtifactStore
from hmap.services.context.base import ContextStore
from hmap.services.registry.base import Registry

log = logging.getLogger("hmap.manager")

S = TaskState
CONSUMER_ID = "manager"

# Project state -> event emitted on entry (custom names follow the dotted event pattern).
PROJECT_STATE_EVENT: dict[ProjectState, str] = {
    ProjectState.CREATED: EventType.PROJECT_CREATED.value,
    ProjectState.AWAITING_APPROVAL: EventType.APPROVAL_REQUESTED.value,
    ProjectState.EXECUTING: "project.executing",
    ProjectState.PLANNING: "project.planning",
    ProjectState.COMPLETED: EventType.PROJECT_COMPLETED.value,
    ProjectState.FAILED: "project.failed",
    ProjectState.CANCELLED: "project.cancelled",
    ProjectState.INGESTING: "project.ingesting",
    ProjectState.REVIEWING: "project.reviewing",
}


# A project in one of these states has work in flight: a new run must wait (or the project be stopped first).
ACTIVE_PROJECT_STATES = frozenset({ProjectState.INGESTING, ProjectState.PLANNING, ProjectState.AWAITING_APPROVAL,
                                   ProjectState.EXECUTING, ProjectState.REVIEWING})


class UnknownProject(KeyError):
    pass


class UnknownTask(KeyError):
    pass


class InvalidProjectState(ValueError):
    pass


class StaleGraph(InvalidProjectState):
    """An approval or replan refers to a plan version that is no longer the project's current one."""


class InvalidTaskState(ValueError):
    """An operator action that does not fit the task's state (e.g. replaying a task that is not dead-lettered)."""


class _Unit:
    """A store transaction plus the events written in it (dispatched to hooks after commit)."""

    def __init__(self, tx: TaskStoreTx) -> None:
        self.tx = tx
        self.events: list[DomainEvent] = []

    async def emit(self, event: DomainEvent) -> None:
        await self.tx.add_event(event)
        self.events.append(event)


class Manager:
    def __init__(self, *, bus: Bus, store: TaskStore, outbox: OutboxStore, registry: Registry,
                 artifacts: ArtifactStore, contexts: ContextStore, plugins: Sequence[Plugin] = (),
                 clock: Callable[[], datetime] = utcnow, config: ManagerConfig | None = None,
                 rng: random.Random | None = None, inbox: InboxStore | None = None) -> None:
        self.bus = bus
        self.store = store
        self.outbox = outbox            # the store writes into it transactionally; used here only by flush_outbox
        self.registry = registry
        self.artifacts = artifacts
        self.contexts = contexts
        self.config = config or ManagerConfig()
        self.plugins = list(plugins)
        self.executor: GraphExecutor = resolve_strategy(self.plugins, "executor", NaiveTopologicalExecutor())
        self.hooks = HookDispatcher(self.plugins)
        self._clock = clock
        self._rng = rng or random.Random()
        self._inbox = inbox
        self._offline_agents: set[str] = set()
        self._assign_lock = asyncio.Lock()
        self._subscription: Subscription | None = None
        self._watchdog_task: asyncio.Task[None] | None = None

    # ============================================================================ lifecycle

    async def start(self, *, watchdog_interval_s: float | None = None) -> None:
        """Consume agent reports; optionally run ``tick`` periodically in the background."""
        # prefetch=1: replies of one execution (ack -> started -> result) must be applied in the order the agent
        # sent them; processing them concurrently could file a result before its ack has committed.
        self._subscription = await self.bus.consume_replies(self.handle_delivery, prefetch=1)
        if watchdog_interval_s:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop(watchdog_interval_s))

    async def stop(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None
        if self._subscription is not None:
            await self._subscription.cancel()
            self._subscription = None

    async def _watchdog_loop(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.tick()
            except Exception:
                log.exception("watchdog tick failed")

    async def flush_outbox(self, limit: int = 100) -> int:
        """Dev/test helper: publish unpublished outbox rows to the bus. Production uses the outbox publisher."""
        n = 0
        for row in await self.outbox.unpublished(limit):
            if row.kind == "command" and isinstance(row.body, Envelope):
                await self.bus.send_command(row.capability or "", row.body)
            elif isinstance(row.body, DomainEvent):
                await self.bus.publish_event(row.body)
            await self.outbox.mark_published(row.seq)
            n += 1
        return n

    # ============================================================================ internals: units, events

    def _now(self) -> datetime:
        return self._clock()

    @asynccontextmanager
    async def _unit(self) -> AsyncIterator[_Unit]:
        async with self.store.transaction() as tx:
            unit = _Unit(tx)
            yield unit
        for event in unit.events:      # after commit only
            await self.hooks.dispatch(event, self)

    def _task_event(self, event_type: str, task: TaskRecord, data: dict[str, Any] | None = None) -> DomainEvent:
        return DomainEvent(
            event_type=event_type, aggregate_id=task.task_id, aggregate_version=task.state_version,
            occurred_at=self._now(), project_id=task.project_id, correlation_id=task.project_id,
            data={"capability": task.capability, "state": task.state.value, "plan_task_id": task.plan_task_id,
                  "execution_id": task.active_execution_id, **(data or {})},
        )

    def _project_event(self, event_type: str, project: ProjectRecord,
                       data: dict[str, Any] | None = None) -> DomainEvent:
        return DomainEvent(
            event_type=event_type, aggregate_id=project.project_id, aggregate_version=project.state_version,
            occurred_at=self._now(), project_id=project.project_id, correlation_id=project.project_id,
            data={"state": project.state.value, "name": project.name, **(data or {})},
        )

    async def _move(self, u: _Unit, task: TaskRecord, to: TaskState, *, data: dict[str, Any] | None = None,
                    operator: bool = False, **changes: Any) -> TaskRecord:
        """Guarded transition: ALLOWED check + CAS + event in the same unit of work. ``operator=True`` (only
        :meth:`replay_dead_letter`) also allows the operator-only edges."""
        check_transition(task.state, to, task.task_id, operator=operator)
        new = task.model_copy(update={"state": to, "updated_at": self._now(), **changes})
        saved = await u.tx.update_task(new, expected_version=task.state_version)
        await u.emit(self._task_event(STATE_EVENT[to].value, saved, data))
        obs_metrics.task_transition(saved.capability, to.value)
        return saved

    async def _move_project(self, u: _Unit, project: ProjectRecord, to: ProjectState, *,
                            data: dict[str, Any] | None = None, **changes: Any) -> ProjectRecord:
        new = project.model_copy(update={"state": to, "updated_at": self._now(), **changes})
        saved = await u.tx.update_project(new, expected_version=project.state_version)
        await u.emit(self._project_event(PROJECT_STATE_EVENT[to], saved, data))
        return saved

    async def _save_execution(self, u: _Unit, exe: ExecutionRecord, **changes: Any) -> ExecutionRecord:
        return await u.tx.update_execution(exe.model_copy(update={"updated_at": self._now(), **changes}))

    async def _after_change(self, project_ids: Iterable[str]) -> None:
        """Post-commit: promote/block graph tasks, settle projects, assign READY work. Errors are logged (the
        triggering change is already durable; the next tick repeats this)."""
        try:
            for pid in sorted(set(project_ids)):
                await self._reconcile_project(pid)
            await self._assign_ready()
        except Exception:
            log.exception("post-change scheduling failed")

    # ============================================================================ ManagerHandle + API

    async def create_project(self, name: str, *, project_id: str | None = None, auto_approve: bool = False,
                             owner_id: str | None = None, description: str | None = None,
                             cloud_ok: bool = True, refine: bool = False) -> str:
        """``auto_approve``: the plan is still created and shown, then approved automatically (no human gate); the
        human keeps the Stop button (:meth:`stop_project`). ``owner_id`` is the user the API will allow.
        ``cloud_ok=False`` keeps every step of the project on local models. ``refine=True`` checks and improves each
        result before it is reported (Sprint 4; copied into ``TaskAssign.refine``)."""
        now = self._now()
        project = ProjectRecord(project_id=project_id or new_project_id(), name=name, created_at=now, updated_at=now,
                                auto_approve=auto_approve, owner_id=owner_id, description=description,
                                cloud_ok=cloud_ok, refine=refine)
        async with self._unit() as u:
            saved = await u.tx.insert_project(project)
            await u.emit(self._project_event(EventType.PROJECT_CREATED.value, saved,
                                             {"auto_approve": auto_approve, "cloud_ok": cloud_ok, "refine": refine}))
        return saved.project_id

    async def list_projects(self, *, owner_id: str | None = None) -> list[dict[str, Any]]:
        """Live (not deleted) projects, optionally only one owner's."""
        return [p.to_dict() for p in await self.store.list_projects(owner_id=owner_id) if p.deleted_at is None]

    async def get_project_record(self, project_id: str) -> ProjectRecord:
        """The record, or :class:`UnknownProject` (also for a deleted project)."""
        p = await self.store.get_project(project_id)
        if p is None or p.deleted_at is not None:
            raise UnknownProject(project_id)
        return p

    async def get_project(self, project_id: str) -> dict[str, Any]:
        p = await self.get_project_record(project_id)
        out = p.to_dict()
        out["approvals"] = [a.to_dict() for a in await self.store.list_approvals(project_id=project_id)]
        return out

    async def start_run(self, project_id: str, *, goal: str | None = None, documents: list[str] | None = None) -> int:
        """Begin a new pipeline pass (an upload or a typed goal). Earlier runs and their tasks stay as history. A
        stopped/finished project can be run again; a project that is still working must finish or be stopped
        first (:class:`InvalidProjectState`). Returns the new run number."""
        now = self._now()
        async with self._unit() as u:
            project = await u.tx.get_project(project_id)
            if project is None or project.deleted_at is not None:
                raise UnknownProject(project_id)
            if project.state in ACTIVE_PROJECT_STATES:
                raise InvalidProjectState(f"project {project_id} is still working ({project.state}); wait for it "
                                          "to finish or stop it first")
            run = RunRecord(number=len(project.runs) + 1, started_at=now, goal=goal, documents=list(documents or []))
            await self._move_project(u, project, ProjectState.INGESTING, runs=[*project.runs, run],
                                     stopped_reason=None, data={"run": run.number})
        return run.number

    async def record_run_documents(self, project_id: str, run: int, artifact_ids: list[str]) -> None:
        """Remember which stored artifact is which document of ``run`` (``documents[i]`` is ``artifact_ids[i]``), so
        the file list can show each upload by its name."""
        async with self._unit() as u:
            project = await u.tx.get_project(project_id)
            if project is None:
                raise UnknownProject(project_id)
            runs = [r.model_copy(update={"document_ids": list(artifact_ids)}) if r.number == run else r
                    for r in project.runs]
            await u.tx.update_project(project.model_copy(update={"runs": runs}),
                                      expected_version=project.state_version)

    async def update_project(self, project_id: str, *, name: str | None = None, archived: bool | None = None,
                             cloud_ok: bool | None = None, refine: bool | None = None) -> dict[str, Any]:
        """Rename, archive, or switch cloud models / refinement on or off. Both switches apply to steps assigned
        after the change."""
        async with self._unit() as u:
            project = await u.tx.get_project(project_id)
            if project is None or project.deleted_at is not None:
                raise UnknownProject(project_id)
            changes: dict[str, Any] = {"updated_at": self._now()}
            if name is not None:
                changes["name"] = name
            if archived is not None:
                changes["archived"] = archived
            if cloud_ok is not None:
                changes["cloud_ok"] = cloud_ok
            if refine is not None:
                changes["refine"] = refine
            saved = await u.tx.update_project(project.model_copy(update=changes),
                                              expected_version=project.state_version)
            await u.emit(self._project_event("project.updated", saved,
                                             {k: v for k, v in changes.items() if k != "updated_at"}))
        return await self.get_project(project_id)

    async def delete_project(self, project_id: str) -> int:
        """Stop any running work, erase the project's files and hide the project from every API. Task, execution,
        approval and event records stay in the database as the audit trail (events are append-only). Returns the
        number of artifact versions erased."""
        project = await self.get_project_record(project_id)
        if project.state in ACTIVE_PROJECT_STATES or project.state == ProjectState.CREATED:
            with contextlib.suppress(InvalidProjectState):
                await self.stop_project(project_id, "project deleted")
        async with self._unit() as u:
            current = await u.tx.get_project(project_id)
            assert current is not None
            saved = await u.tx.update_project(current.model_copy(update={"deleted_at": self._now(),
                                                                         "updated_at": self._now()}),
                                              expected_version=current.state_version)
            await u.emit(self._project_event("project.deleted", saved))
        return await self.artifacts.delete_project(project_id)

    async def list_tasks(self, project_id: str) -> list[dict[str, Any]]:
        return [t.to_dict() for t in await self.store.list_tasks(project_id=project_id)]

    async def get_task(self, task_id: str) -> dict[str, Any]:
        t = await self.store.get_task(task_id)
        if t is None:
            raise UnknownTask(task_id)
        out = t.to_dict()
        out["executions"] = [e.to_dict() for e in await self.store.list_executions(task_id=task_id)]
        return out

    async def list_executions(self, task_id: str) -> list[dict[str, Any]]:
        return [e.to_dict() for e in await self.store.list_executions(task_id=task_id)]

    async def emit(self, event: DomainEvent) -> None:
        async with self._unit() as u:
            await u.emit(event)

    async def create_task(self, project_id: str, capability: str, objective: str, *,
                          acceptance_criteria: list[str] | None = None, inputs: dict[str, Any] | None = None,
                          artifact_refs: list[ArtifactRef] | None = None, depends_on: list[str] | None = None,
                          parent_task_id: str | None = None) -> str:
        if not objective.strip():
            raise ValueError("objective must not be empty")
        project = await self.store.get_project(project_id)
        if project is None:
            raise UnknownProject(project_id)
        self._ensure_not_stopped(project)
        for dep in depends_on or []:
            if await self.store.get_task(dep) is None:
                raise UnknownTask(dep)
        now = self._now()
        task = TaskRecord(task_id=new_task_id(), project_id=project_id, capability=capability, objective=objective,
                          run=project.current_run,
                          acceptance_criteria=list(acceptance_criteria or []), inputs=dict(inputs or {}),
                          artifact_refs=list(artifact_refs or []), depends_on=list(depends_on or []),
                          parent_task_id=parent_task_id, created_at=now, updated_at=now)
        async with self._unit() as u:
            current = await u.tx.get_project(project_id)
            if current is not None:
                self._ensure_not_stopped(current)      # Stop pressed in the meantime
            saved = await u.tx.insert_task(task)
            await u.emit(self._task_event(EventType.TASK_CREATED.value, saved))
        await self._after_change([project_id])
        return saved.task_id

    async def submit_graph(self, project_id: str, graph: TaskGraph, *, require_approval: bool = True) -> None:
        project = await self.store.get_project(project_id)
        if project is None:
            raise UnknownProject(project_id)
        self._ensure_not_stopped(project)
        auto = require_approval and project.auto_approve
        gated = require_approval and not auto
        order = self.executor.order(graph)
        mapping = {pid: new_task_id() for pid in order}
        now = self._now()
        async with self._unit() as u:
            for pid in order:
                pt = graph.task(pid)
                task = TaskRecord(
                    task_id=mapping[pid], project_id=project_id, capability=pt.agent_capability,
                    objective=pt.description or pt.title, title=pt.title,
                    acceptance_criteria=list(pt.acceptance_criteria),
                    inputs={"plan_task_id": pid, "requirement_ids": list(pt.requirement_ids), "phase": pt.phase,
                            "research_questions": list(pt.research_questions), "graph_version": graph.version},
                    depends_on=[mapping[d] for d in pt.depends_on], plan_task_id=pid, priority=pt.priority,
                    run=project.current_run,
                    needs_approval=gated, created_at=now, updated_at=now)
                saved = await u.tx.insert_task(task)
                await u.emit(self._task_event(EventType.TASK_CREATED.value, saved))
            current = await u.tx.get_project(project_id)
            assert current is not None
            self._ensure_not_stopped(current)          # Stop pressed while this graph was being built
            changes: dict[str, Any] = {"graph_version": graph.version, "plan_task_map": mapping}
            if auto:
                approval = ApprovalRecord(approval_id=new_uuid(), project_id=project_id, graph_version=graph.version,
                                          status="approved", comment="auto-approved (project setting)",
                                          requested_at=now, decided_at=now)
                await u.tx.insert_approval(approval)
                await u.emit(self._project_event(EventType.APPROVAL_DECIDED.value, current, {
                    "approved": True, "auto": True, "comment": approval.comment,
                    "approval_ids": [approval.approval_id], "graph_version": graph.version}))
                await self._move_project(u, current, ProjectState.EXECUTING, **changes, data={
                    "graph_version": graph.version, "task_count": len(order), "auto_approved": True})
            elif gated:
                approval = ApprovalRecord(approval_id=new_uuid(), project_id=project_id,
                                          graph_version=graph.version, requested_at=now)
                await u.tx.insert_approval(approval)
                await self._move_project(u, current, ProjectState.AWAITING_APPROVAL, **changes, data={
                    "approval_id": approval.approval_id, "graph_version": graph.version, "task_count": len(order)})
            else:
                await self._move_project(u, current, ProjectState.EXECUTING, **changes,
                                         data={"graph_version": graph.version, "task_count": len(order)})
        await self._after_change([project_id])

    async def approve(self, project_id: str, approved: bool, comment: str | None = None, *,
                      graph_version: int | None = None) -> None:
        """Human plan-approval gate. Approve -> graph tasks may start; reject -> they are cancelled and the project
        goes back to PLANNING (a new graph can be submitted). With ``graph_version``, a decision about an older plan
        (replanned meanwhile) raises :class:`StaleGraph`."""
        now = self._now()
        async with self._unit() as u:
            project = await u.tx.get_project(project_id)
            if project is None:
                raise UnknownProject(project_id)
            if project.state != ProjectState.AWAITING_APPROVAL:
                raise InvalidProjectState(f"project {project_id} is {project.state}, not AWAITING_APPROVAL")
            if graph_version is not None and graph_version != project.graph_version:
                raise StaleGraph(f"plan version {graph_version} was replaced by version {project.graph_version}")
            pending = [a for a in await u.tx.list_approvals(project_id=project_id) if a.status == "pending"]
            for a in pending:
                await u.tx.update_approval(a.model_copy(update={
                    "status": "approved" if approved else "rejected", "comment": comment, "decided_at": now}))
            await u.emit(self._project_event(EventType.APPROVAL_DECIDED.value, project, {
                "approved": approved, "comment": comment, "approval_ids": [a.approval_id for a in pending],
                "graph_version": project.graph_version}))
            for t in await u.tx.list_tasks(project_id=project_id):
                if not t.needs_approval:
                    continue
                if approved:
                    await u.tx.update_task(t.model_copy(update={"needs_approval": False, "updated_at": now}),
                                           expected_version=t.state_version)
                elif not is_terminal(t.state):
                    await self._move(u, t, S.CANCELLED, needs_approval=False,
                                     data={"reason": "plan rejected", "comment": comment})
            await self._move_project(u, project, ProjectState.EXECUTING if approved else ProjectState.PLANNING)
        await self._after_change([project_id])

    async def replace_graph(self, project_id: str, graph: TaskGraph, *,
                            require_approval: bool = True) -> dict[str, str]:
        """Replanning (Sprint 3): swap the current run's plan for ``graph`` and keep finished work. A plan task whose
        id is still in ``graph`` and that is COMPLETED or in flight keeps its task (and result); every other
        unfinished task of the old plan is cancelled ("replanned"), and all dropped tasks are marked ``replaced`` so
        the executor and the project outcome ignore them. New tasks are created, and the approval gate applies again
        (auto-approve projects continue at once). ``graph.version`` must be newer than the current plan's
        (:class:`StaleGraph`). Without a current plan this is :meth:`submit_graph`. Returns plan id -> task id."""
        project = await self.store.get_project(project_id)
        if project is None:
            raise UnknownProject(project_id)
        self._ensure_not_stopped(project)
        if project.graph_version is None:
            await self.submit_graph(project_id, graph, require_approval=require_approval)
            return dict((await self.store.get_project(project_id) or project).plan_task_map)
        if graph.version <= project.graph_version:
            raise StaleGraph(f"plan version {graph.version} is not newer than the current version "
                             f"{project.graph_version}")
        auto = require_approval and project.auto_approve
        gated = require_approval and not auto
        order = self.executor.order(graph)
        keep_states = {S.COMPLETED} | IN_FLIGHT_STATES | {S.RESULT_SUBMITTED, S.REVIEWING, S.NEEDS_REVISION,
                                                         S.RETRY_SCHEDULED}
        now = self._now()
        reason = f"replanned (plan version {graph.version})"
        async with self._unit() as u:
            current = await u.tx.get_project(project_id)
            assert current is not None
            self._ensure_not_stopped(current)
            run = current.current_run
            old = [t for t in await u.tx.list_tasks(project_id=project_id)
                   if t.run == run and t.plan_task_id is not None and not t.replaced]
            new_ids = {t.id for t in graph.tasks}
            kept = {t.plan_task_id: t for t in old if t.plan_task_id in new_ids and t.state in keep_states}
            mapping = {pid: kept[pid].task_id if pid in kept else new_task_id() for pid in order}
            for t in old:
                if t.plan_task_id in kept:
                    await u.tx.update_task(t.model_copy(update={
                        "inputs": {**t.inputs, "graph_version": graph.version}, "updated_at": now}),
                        expected_version=t.state_version)
                    continue
                if is_terminal(t.state):
                    await u.tx.update_task(t.model_copy(update={"replaced": True, "updated_at": now}),
                                           expected_version=t.state_version)
                    continue
                agent_id = None
                if t.active_execution_id:
                    exe = await u.tx.get_execution(t.active_execution_id)
                    if exe is not None and exe.status in IN_FLIGHT_EXECUTIONS:
                        agent_id = exe.agent_id
                        await self._save_execution(u, exe, status=ExecutionStatus.CANCELLED,
                                                   error={"code": ErrorCode.CANCELLED.value, "message": reason})
                await self._move(u, t, S.CANCELLED, needs_approval=False, replaced=True,
                                 data={"reason": reason, "agent_id": agent_id, "replanned": True})
            for pid in order:
                if pid in kept:
                    continue
                pt = graph.task(pid)
                task = TaskRecord(
                    task_id=mapping[pid], project_id=project_id, capability=pt.agent_capability,
                    objective=pt.description or pt.title, title=pt.title,
                    acceptance_criteria=list(pt.acceptance_criteria),
                    inputs={"plan_task_id": pid, "requirement_ids": list(pt.requirement_ids), "phase": pt.phase,
                            "research_questions": list(pt.research_questions), "graph_version": graph.version},
                    depends_on=[mapping[d] for d in pt.depends_on], plan_task_id=pid, priority=pt.priority,
                    run=run, needs_approval=gated, created_at=now, updated_at=now)
                saved = await u.tx.insert_task(task)
                await u.emit(self._task_event(EventType.TASK_CREATED.value, saved))
            for a in await u.tx.list_approvals(project_id=project_id):
                if a.status == "pending":
                    await u.tx.update_approval(a.model_copy(update={
                        "status": "rejected", "comment": f"superseded by plan version {graph.version}",
                        "decided_at": now}))
            current = await u.tx.get_project(project_id)
            assert current is not None
            runs = list(current.runs)
            if runs and runs[-1].outcome is not None:      # a finished run is working again
                runs[-1] = runs[-1].model_copy(update={"outcome": None, "finished_at": None})
            changes: dict[str, Any] = {"graph_version": graph.version, "plan_task_map": mapping, "runs": runs}
            info = {"graph_version": graph.version, "task_count": len(order), "replanned": True,
                    "kept_tasks": len(kept)}
            if auto:
                approval = ApprovalRecord(approval_id=new_uuid(), project_id=project_id, graph_version=graph.version,
                                          status="approved", comment="auto-approved (project setting)",
                                          requested_at=now, decided_at=now)
                await u.tx.insert_approval(approval)
                await u.emit(self._project_event(EventType.APPROVAL_DECIDED.value, current, {
                    "approved": True, "auto": True, "comment": approval.comment,
                    "approval_ids": [approval.approval_id], "graph_version": graph.version}))
                await self._move_project(u, current, ProjectState.EXECUTING, **changes,
                                         data={**info, "auto_approved": True})
            elif gated:
                approval = ApprovalRecord(approval_id=new_uuid(), project_id=project_id,
                                          graph_version=graph.version, requested_at=now)
                await u.tx.insert_approval(approval)
                await self._move_project(u, current, ProjectState.AWAITING_APPROVAL, **changes,
                                         data={**info, "approval_id": approval.approval_id})
            else:
                await self._move_project(u, current, ProjectState.EXECUTING, **changes, data=info)
        await self._after_change([project_id])
        return mapping

    async def cancel_task(self, task_id: str, reason: str) -> bool:
        """CANCELLED + ``task.cancelled`` event (agents listen for it and stop cooperatively). A result that
        arrives later is retained as evidence, never final. Returns False if the task was already terminal."""
        async with self._unit() as u:
            task = await u.tx.get_task(task_id)
            if task is None:
                raise UnknownTask(task_id)
            if is_terminal(task.state):
                return False
            agent_id = None
            if task.active_execution_id:
                exe = await u.tx.get_execution(task.active_execution_id)
                if exe is not None and exe.status in IN_FLIGHT_EXECUTIONS:
                    agent_id = exe.agent_id
                    await self._save_execution(u, exe, status=ExecutionStatus.CANCELLED,
                                               error={"code": ErrorCode.CANCELLED.value, "message": reason})
            await self._move(u, task, S.CANCELLED, data={"reason": reason, "agent_id": agent_id})
        await self._after_change([task.project_id])
        return True

    async def stop_project(self, project_id: str, reason: str = "stopped by user") -> int:
        """The human's Stop button: cancel every unfinished task (agents get ``task.cancelled`` and stop
        cooperatively; late results are kept as evidence only), close pending approvals and move the project to
        CANCELLED. Afterwards hooks cannot add work (:class:`ProjectStopped`). Returns the number of cancelled tasks;
        raises :class:`InvalidProjectState` if the project already finished."""
        now = self._now()
        async with self._unit() as u:
            project = await u.tx.get_project(project_id)
            if project is None:
                raise UnknownProject(project_id)
            if project.state in (ProjectState.COMPLETED, ProjectState.FAILED, ProjectState.CANCELLED):
                raise InvalidProjectState(f"project {project_id} is already {project.state}")
            cancelled = 0
            for task in await u.tx.list_tasks(project_id=project_id):
                if is_terminal(task.state):
                    continue
                agent_id = None
                if task.active_execution_id:
                    exe = await u.tx.get_execution(task.active_execution_id)
                    if exe is not None and exe.status in IN_FLIGHT_EXECUTIONS:
                        agent_id = exe.agent_id
                        await self._save_execution(u, exe, status=ExecutionStatus.CANCELLED,
                                                   error={"code": ErrorCode.CANCELLED.value, "message": reason})
                await self._move(u, task, S.CANCELLED, needs_approval=False,
                                 data={"reason": reason, "agent_id": agent_id, "project_stopped": True})
                cancelled += 1
            for a in await u.tx.list_approvals(project_id=project_id):
                if a.status == "pending":
                    await u.tx.update_approval(a.model_copy(update={
                        "status": "rejected", "comment": f"project stopped: {reason}", "decided_at": now}))
            await self._move_project(u, project, ProjectState.CANCELLED, stopped_reason=reason,
                                     runs=self._settled_runs(project, ProjectState.CANCELLED, now),
                                     data={"reason": reason, "cancelled_tasks": cancelled})
        await self._after_change([project_id])
        return cancelled

    async def replay_dead_letter(self, task_id: str, *, operator: str, reason: str) -> dict[str, Any]:
        """An operator replays a dead-lettered task (Sprint 4 item 4.18, plan D18; research §26: never automatic,
        never blind). The task goes ``DEAD_LETTERED → READY`` (an operator-only edge) with its retry budget reset; the
        assignment that follows creates a NEW execution (the attempt counter continues, the dead-lettered execution
        keeps its record). Tasks that were blocked waiting on it go ``BLOCKED → CREATED`` and are re-evaluated; a
        project that had failed because of it goes back to EXECUTING. Audited with ``task.replayed {by, reason}``.

        Raises :class:`UnknownTask`, :class:`InvalidTaskState` (not dead-lettered, replaced by a newer plan, or from
        an earlier run) and :class:`ProjectStopped` (the project was stopped)."""
        if not reason.strip():
            raise ValueError("a replay needs a reason (it is kept in the audit trail)")
        now = self._now()
        async with self._unit() as u:
            task = await u.tx.get_task(task_id)
            if task is None:
                raise UnknownTask(task_id)
            project = await u.tx.get_project(task.project_id)
            if project is None or project.deleted_at is not None:
                raise UnknownTask(task_id)
            self._ensure_not_stopped(project)
            if task.state != S.DEAD_LETTERED:
                raise InvalidTaskState(f"task {task_id} is {task.state}, not DEAD_LETTERED: only dead letters can be "
                                       "replayed")
            if task.replaced:
                raise InvalidTaskState(f"task {task_id} was replaced by a newer plan; replan instead of replaying")
            if task.run != project.current_run:
                raise InvalidTaskState(f"task {task_id} belongs to run {task.run}; the project is on run "
                                       f"{project.current_run} (run it again instead)")
            replay = task.replays + 1
            info = {"by": operator, "reason": reason.strip()[:500], "replay": replay,
                    "previous_attempts": task.attempts, "last_error": task.last_error}
            saved = await self._move(u, task, S.READY, operator=True, retries=0, rejections=0, rejected_by=[],
                                     retry_at=None, blocked_by=[], replays=replay,
                                     data={"reason": "replayed by an operator", "replay": replay})
            await u.emit(self._task_event(EventType.TASK_REPLAYED.value, saved, info))
            obs_metrics.REPLAYS.labels(saved.capability).inc()
            # tasks that were waiting on it (directly or through another blocked task) are evaluated again
            tasks = [t for t in await u.tx.list_tasks(project_id=task.project_id) if not t.replaced]
            closure = {task_id}
            changed = True
            while changed:
                changed = False
                for t in tasks:
                    # blocked by a dependency (blocked_by = task ids), not by its own error (blocked_by = a code)
                    if t.task_id not in closure and t.state == S.BLOCKED and set(t.depends_on) & closure \
                            and set(t.blocked_by) <= set(t.depends_on):
                        closure.add(t.task_id)
                        changed = True
            unblocked = []
            for t in tasks:
                if t.task_id in closure and t.task_id != task_id:
                    await self._move(u, t, S.CREATED, operator=True, blocked_by=[],
                                     data={"reason": f"dependency {task_id} replayed", "replayed": task_id})
                    unblocked.append(t.task_id)
            current = await u.tx.get_project(task.project_id)
            assert current is not None
            if current.state == ProjectState.FAILED:
                runs = list(current.runs)
                if runs and runs[-1].outcome is not None:
                    runs[-1] = runs[-1].model_copy(update={"outcome": None, "finished_at": None})
                await self._move_project(u, current, ProjectState.EXECUTING, runs=runs,
                                         data={"reason": "dead letter replayed", "task_id": task_id})
        await self._after_change([task.project_id])
        log.info("task %s replayed by %s (replay %d, %d dependants re-evaluated)", task_id, operator, replay,
                 len(unblocked))
        return {"task_id": task_id, "replay": replay, "unblocked": unblocked, "replayed_at": now.isoformat(),
                "task": await self.get_task(task_id)}

    @staticmethod
    def _ensure_not_stopped(project: ProjectRecord) -> None:
        if project.state == ProjectState.CANCELLED:
            raise ProjectStopped(f"project {project.project_id} was stopped; no new work is accepted")

    # ============================================================================ reply consumption

    async def handle_delivery(self, delivery: Delivery) -> None:
        """Bus handler for ``hmap.manager``. Ack only after the state change is committed."""
        body = delivery.body
        if not isinstance(body, Envelope):
            await delivery.ack()
            return
        if self._inbox is not None and await self._inbox.seen(CONSUMER_ID, body.message_id):
            obs_metrics.DEDUP_HITS.labels(CONSUMER_ID).inc()
            await delivery.ack()
            return
        try:
            payload = body.typed_payload()
        except (ValidationError, HmapError) as exc:
            await delivery.reject(f"invalid payload: {exc}")
            return
        obs_metrics.REPORTS.labels(body.message_type).inc()
        try:
            if body.task_id and body.message_type not in ("agent.heartbeat", "task.progress"):
                with telemetry.span(f"manager.handle {body.message_type}", kind="consumer", parent=body.traceparent,
                                    attrs={"hmap.task_id": body.task_id, "hmap.execution_id": body.execution_id,
                                           "messaging.message.id": body.message_id,
                                           "hmap.sender": body.sender.agent_id}):
                    await self.handle_message(body, payload)
            else:
                await self.handle_message(body, payload)
        except StoreError as exc:      # CAS lost to a concurrent writer: redeliver, the guards make it idempotent
            log.warning("store conflict on %s %s: %s", body.message_type, body.message_id, exc)
            await delivery.nack(requeue=True)
            return
        except Exception as exc:
            log.exception("failed to handle %s %s", body.message_type, body.message_id)
            await delivery.reject(f"{type(exc).__name__}: {exc}")
            return
        if self._inbox is not None:
            await self._inbox.record(CONSUMER_ID, body.message_id)
        await delivery.ack()

    async def handle_message(self, env: Envelope, payload: Contract) -> None:
        """Apply one agent report. Also usable directly (tests, an HTTP fallback)."""
        if isinstance(payload, AgentRegister):
            await self._on_register(payload)
        elif isinstance(payload, AgentHeartbeat):
            await self._on_heartbeat(payload)
        elif isinstance(payload, AgentDeregister):
            await self._on_deregister(payload)
        elif isinstance(payload, TaskAck):
            await self._on_ack(env, payload)
        elif isinstance(payload, TaskStarted):
            await self._on_started(env, payload)
        elif isinstance(payload, TaskProgress):
            await self._on_progress(env, payload)
        elif isinstance(payload, TaskResult):
            await self._on_result(env, payload)
        elif isinstance(payload, ErrorPayload):
            await self._on_error(env, payload)
        elif isinstance(payload, RetryRequest):
            await self._on_retry_request(env, payload)
        else:
            log.info("manager ignores %s from %s", env.message_type, env.sender.agent_id)

    # ---------------------------------------------------------------- helpers for execution reports

    @staticmethod
    def _is_active(task: TaskRecord, exe: ExecutionRecord) -> bool:
        return (task.active_execution_id == exe.execution_id and not is_terminal(task.state)
                and exe.status in IN_FLIGHT_EXECUTIONS)

    async def _load(self, u: _Unit, execution_id: str) -> tuple[TaskRecord, ExecutionRecord] | None:
        exe = await u.tx.get_execution(execution_id)
        if exe is None:
            log.warning("report for unknown execution %s", execution_id)
            return None
        task = await u.tx.get_task(exe.task_id)
        if task is None:  # pragma: no cover - referential integrity
            return None
        return task, exe

    async def _evidence(self, u: _Unit, task: TaskRecord, exe: ExecutionRecord, env: Envelope, note: str) -> None:
        """Late / stale / superseded report: keep it on the execution, change nothing else (research §17)."""
        entry = {"message_type": env.message_type, "message_id": env.message_id, "sender": env.sender.agent_id,
                 "received_at": self._now().isoformat(), "task_state": task.state.value, "note": note,
                 "payload": env.payload}
        await self._save_execution(u, exe, evidence=[*exe.evidence, entry])
        log.info("recorded %s for %s as evidence (%s)", env.message_type, exe.execution_id, note)

    async def _fail(self, u: _Unit, task: TaskRecord, exe: ExecutionRecord, code: ErrorCode | str, message: str, *,
                    now: datetime, agent_says_retryable: bool | None = None,
                    exe_status: ExecutionStatus = ExecutionStatus.FAILED,
                    requested_delay_s: float | None = None) -> TaskRecord:
        """Apply the retry policy to a failed active execution."""
        d = decide(code, retries_used=task.retries, config=self.config, rng=self._rng,
                   agent_says_retryable=agent_says_retryable, requested_delay_s=requested_delay_s)
        error = {"code": str(code), "message": message, "execution_id": exe.execution_id, "attempt": exe.attempt,
                 "agent_id": exe.agent_id, "action": d.action.value, "at": now.isoformat()}
        if d.action == FailureAction.RETRY:
            await self._save_execution(u, exe, status=exe_status, error=error)
            retry_at = now + timedelta(seconds=d.delay_s)
            return await self._move(u, task, S.RETRY_SCHEDULED, active_execution_id=None, retries=task.retries + 1,
                                    rejections=0, retry_at=retry_at, last_error=error,
                                    data={"error": error, "retry": task.retries + 1, "delay_s": d.delay_s,
                                          "retry_at": retry_at.isoformat()})
        if d.action == FailureAction.DEAD_LETTER:
            await self._save_execution(u, exe, status=ExecutionStatus.DEAD_LETTERED, error=error)
            history = [e.error for e in await u.tx.list_executions(task_id=task.task_id) if e.error]
            return await self._move(u, task, S.DEAD_LETTERED, active_execution_id=None, last_error=error,
                                    data={"error": error, "history": history, "attempts": task.attempts,
                                          "needs_review": True})
        await self._save_execution(u, exe, status=ExecutionStatus.FAILED, error=error)
        if d.action == FailureAction.BLOCK:
            return await self._move(u, task, S.BLOCKED, active_execution_id=None, last_error=error,
                                    blocked_by=[str(code)], data={"error": error})
        return await self._move(u, task, S.FAILED, active_execution_id=None, last_error=error, data={"error": error})

    # ---------------------------------------------------------------- execution reports

    async def _on_ack(self, env: Envelope, p: TaskAck) -> None:
        sender = env.sender.agent_id
        async with self._unit() as u:
            loaded = await self._load(u, p.execution_id)
            if loaded is None:
                return
            task, exe = loaded
            if not self._is_active(task, exe) or task.state != S.ASSIGNED:
                await self._evidence(u, task, exe, env, "ack for non-active execution or out of order")
                return
            if p.decision == "accepted":
                await self._save_execution(u, exe, status=ExecutionStatus.ACTIVE, agent_id=sender, lease_until=None)
                await self._move(u, task, S.ACCEPTED, data={"agent_id": sender})
            else:
                rejections = task.rejections + 1
                rejected_by = sorted({*task.rejected_by, sender})
                if rejections >= self.config.max_rejections:
                    task = task.model_copy(update={"rejections": rejections, "rejected_by": rejected_by})
                    await self._fail(u, task, exe, ErrorCode.AGENT_UNAVAILABLE,
                                     f"assignment rejected {rejections}x: {p.reason}", now=self._now())
                else:
                    await self._save_execution(u, exe, status=ExecutionStatus.SUPERSEDED, error={
                        "code": "REJECTED", "message": p.reason or "rejected", "agent_id": sender})
                    await self._move(u, task, S.READY, active_execution_id=None, rejections=rejections,
                                     rejected_by=rejected_by, data={"reason": "rejected", "agent_id": sender,
                                                                    "detail": p.reason})
        await self._after_change([task.project_id])

    async def _on_started(self, env: Envelope, p: TaskStarted) -> None:
        async with self._unit() as u:
            loaded = await self._load(u, p.execution_id)
            if loaded is None:
                return
            task, exe = loaded
            if not self._is_active(task, exe) or classify(task.state, S.RUNNING) != "apply":
                await self._evidence(u, task, exe, env, "late or stale task.started")
                return
            await self._save_execution(u, exe, status=ExecutionStatus.ACTIVE, agent_id=env.sender.agent_id,
                                       lease_until=None)
            await self._move(u, task, S.RUNNING, data={"agent_id": env.sender.agent_id})
        await self._after_change([task.project_id])

    async def _on_progress(self, env: Envelope, p: TaskProgress) -> None:
        async with self._unit() as u:
            loaded = await self._load(u, p.execution_id)
            if loaded is None:
                return
            task, exe = loaded
            if not self._is_active(task, exe) or task.state not in IN_FLIGHT_STATES:
                return  # progress is at-most-once telemetry: drop stale ones
            await u.emit(self._task_event(EventType.TASK_PROGRESS.value, task, {
                "percent": p.percent, "summary": p.summary,
                "artifact_refs": [r.model_dump(mode="json") for r in p.artifact_refs]}))

    async def _on_result(self, env: Envelope, p: TaskResult) -> None:
        async with self._unit() as u:
            loaded = await self._load(u, p.execution_id)
            if loaded is None:
                return
            task, exe = loaded
            if not self._is_active(task, exe) or classify(task.state, S.RESULT_SUBMITTED) != "apply":
                await self._evidence(u, task, exe, env, "result from a non-active execution")
                return
            refs = [r.model_dump(mode="json") for r in p.artifact_refs]
            failed = p.outcome == "failure"
            exe = await self._save_execution(
                u, exe, status=ExecutionStatus.FAILED if failed else ExecutionStatus.SUCCEEDED,
                agent_id=env.sender.agent_id, outcome=p.outcome, result_refs=list(p.artifact_refs),
                result_summary=p.summary, lease_until=None, orphaned_at=None)
            task = await self._move(u, task, S.RESULT_SUBMITTED,
                                    data={"outcome": p.outcome, "artifact_refs": refs, "summary": p.summary})
            # Sprint 1: no reviewer configured -> straight to the final state.
            if failed:
                error = {"code": ErrorCode.WRONG_RESULT.value, "message": p.summary or "agent reported failure",
                         "execution_id": exe.execution_id, "attempt": exe.attempt}
                await self._save_execution(u, exe, error=error)
                await self._move(u, task, S.FAILED, last_error=error, data={"error": error, "artifact_refs": refs})
            else:
                await self._move(u, task, S.COMPLETED, data={"outcome": p.outcome, "artifact_refs": refs,
                                                             "summary": p.summary, "evidence": p.evidence})
        await self._after_change([task.project_id])

    async def _on_error(self, env: Envelope, p: ErrorPayload) -> None:
        async with self._unit() as u:
            loaded = await self._load(u, p.execution_id)
            if loaded is None:
                return
            task, exe = loaded
            if not self._is_active(task, exe):
                await self._evidence(u, task, exe, env, "error from a non-active execution")
                return
            status = ExecutionStatus.TIMED_OUT if p.error_code == ErrorCode.TIMEOUT else ExecutionStatus.FAILED
            await self._fail(u, task, exe, p.error_code, p.message, now=self._now(),
                             agent_says_retryable=p.retryable, exe_status=status)
        await self._after_change([task.project_id])

    async def _on_retry_request(self, env: Envelope, p: RetryRequest) -> None:
        async with self._unit() as u:
            loaded = await self._load(u, p.execution_id)
            if loaded is None:
                return
            task, exe = loaded
            if not self._is_active(task, exe):
                await self._evidence(u, task, exe, env, "retry.request from a non-active execution")
                return
            await self._fail(u, task, exe, ErrorCode.TOOL_TRANSIENT, f"retry requested: {p.reason}",
                             now=self._now(), agent_says_retryable=True,
                             requested_delay_s=float(p.requested_delay_seconds or 0))
        await self._after_change([task.project_id])

    # ---------------------------------------------------------------- agent lifecycle reports

    def _agent_event(self, event_type: EventType, agent_id: str, version: int, data: dict[str, Any]) -> DomainEvent:
        return DomainEvent(event_type=event_type.value, aggregate_id=agent_id, aggregate_version=version,
                           occurred_at=self._now(), data=data)

    async def _on_register(self, p: AgentRegister) -> None:
        rec = await self.registry.register(p)   # SchemaUnsupported -> delivery rejected
        self._offline_agents.discard(p.agent_id)
        now = self._now()
        async with self._unit() as u:
            await u.emit(self._agent_event(EventType.AGENT_REGISTERED, rec.agent_id, rec.state_version, {
                "capabilities": rec.capabilities, "is_stub": rec.is_stub, "plugin": rec.plugin,
                "protocol_version": rec.protocol_version, "max_slots": rec.max_slots}))
            # A (re-)registration is a fresh instance: its earlier in-flight work is suspect. Start the grace
            # period; a heartbeat that lists the execution clears it.
            for exe in await u.tx.list_executions(agent_id=p.agent_id, statuses=IN_FLIGHT_EXECUTIONS):
                if exe.orphaned_at is None:
                    await self._save_execution(u, exe, orphaned_at=now)
        await self._assign_ready()

    async def _on_heartbeat(self, p: AgentHeartbeat) -> None:
        rec = await self.registry.heartbeat(p)
        if rec is None:
            log.info("heartbeat from unknown agent %s: it must re-register", p.agent_id)
            return
        listed = set(p.current_execution_ids)
        async with self._unit() as u:
            if p.agent_id in self._offline_agents:
                self._offline_agents.discard(p.agent_id)
                await u.emit(self._agent_event(EventType.AGENT_RECOVERED, rec.agent_id, rec.state_version,
                                               {"state": rec.state.value}))
            for exe in await u.tx.list_executions(agent_id=p.agent_id, statuses=IN_FLIGHT_EXECUTIONS):
                if exe.execution_id in listed and (exe.orphaned_at is not None or
                                                   exe.status == ExecutionStatus.ACTIVE):
                    await self._save_execution(u, exe, orphaned_at=None,
                                               lease_until=rec.lease_until if exe.status == ExecutionStatus.ACTIVE
                                               else exe.lease_until)
        await self._assign_ready()

    async def _on_deregister(self, p: AgentDeregister) -> None:
        await self.registry.deregister(p.agent_id, p.reason)
        now = self._now()
        async with self._unit() as u:
            await u.emit(self._agent_event(EventType.AGENT_OFFLINE, p.agent_id, 0,
                                           {"reason": p.reason, "deregistered": True}))
            for exe in await u.tx.list_executions(agent_id=p.agent_id, statuses=IN_FLIGHT_EXECUTIONS):
                if exe.orphaned_at is None:
                    await self._save_execution(u, exe, orphaned_at=now)

    # ============================================================================ watchdog

    async def tick(self, now: datetime | None = None) -> None:
        """Periodic housekeeping: ack timeouts, lease expiry + abandoned executions, due retries, graph
        progress, assignment. Safe to call at any frequency."""
        now = now or self._now()
        touched: set[str] = set()

        # 1. assigned but never acked -> retryable TIMEOUT
        for exe in ack_timed_out(await self.store.list_executions(statuses={ExecutionStatus.PENDING}), now):
            touched |= await self._timeout_execution(exe.execution_id, ErrorCode.TIMEOUT, "no task.ack before "
                                                     "the ack deadline", now, require_state=S.ASSIGNED)

        # 2. registry leases; executions on agents that are gone -> grace period -> retry
        for rec in await self.registry.expire_leases(now):
            self._offline_agents.add(rec.agent_id)
            await self.emit(self._agent_event(EventType.AGENT_OFFLINE, rec.agent_id, rec.state_version,
                                              {"reason": "lease expired", "lease_until": rec.lease_until.isoformat()}))
        agents = {r.agent_id: r for r in await self.registry.list()}
        scan = scan_orphans(await self.store.list_executions(statuses=IN_FLIGHT_EXECUTIONS), agents, now,
                            timedelta(seconds=self.config.offline_grace_s))
        if scan.newly_orphaned or scan.recovered:
            async with self._unit() as u:
                for exe in scan.newly_orphaned:
                    await self._save_execution(u, exe, orphaned_at=now)
                for exe in scan.recovered:
                    await self._save_execution(u, exe, orphaned_at=None)
        for exe in scan.abandoned:
            touched |= await self._timeout_execution(exe.execution_id, ErrorCode.AGENT_UNAVAILABLE,
                                                     f"agent {exe.agent_id} offline past the grace period", now)

        # 3. retries whose backoff elapsed -> READY (a new execution is created on assignment)
        for task in await self.store.list_tasks(states={S.RETRY_SCHEDULED}):
            if task.retry_at is None or task.retry_at <= now:
                async with self._unit() as u:
                    current = await u.tx.get_task(task.task_id)
                    if current is not None and current.state == S.RETRY_SCHEDULED:
                        await self._move(u, current, S.READY, retry_at=None, data={"reason": "retry due"})
                        touched.add(current.project_id)

        # 4. graph progress for every live project, then assignment
        for project in await self.store.list_projects():
            if project.state not in (ProjectState.COMPLETED, ProjectState.FAILED, ProjectState.CANCELLED):
                touched.add(project.project_id)
        await self._after_change(touched)

    async def _timeout_execution(self, execution_id: str, code: ErrorCode, message: str, now: datetime, *,
                                 require_state: TaskState | None = None) -> set[str]:
        async with self._unit() as u:
            loaded = await self._load(u, execution_id)
            if loaded is None:
                return set()
            task, exe = loaded
            if not self._is_active(task, exe) or (require_state is not None and task.state != require_state):
                return set()
            await self._fail(u, task, exe, code, message, now=now, exe_status=ExecutionStatus.TIMED_OUT)
        return {task.project_id}

    # ============================================================================ graph progress + assignment

    async def _reconcile_project(self, project_id: str) -> None:
        for _ in range(1000):  # each pass changes >= 1 task; bounded for safety
            tasks = [t for t in await self.store.list_tasks(project_id=project_id) if not t.replaced]
            blocked = self.executor.blocked(tasks)
            ready = self.executor.ready(tasks)
            if not blocked and not ready:
                break
            changed = False
            async with self._unit() as u:
                for tid, deps in blocked.items():
                    t = await u.tx.get_task(tid)
                    if t is not None and t.state == S.CREATED:
                        await self._move(u, t, S.BLOCKED, blocked_by=deps,
                                         data={"reason": "dependency cannot complete", "blocked_by": deps})
                        changed = True
                for tid in ready:
                    t = await u.tx.get_task(tid)
                    if t is not None and t.state == S.CREATED and tid not in blocked:
                        await self._move(u, t, S.READY, data={"reason": "dependencies complete"})
                        changed = True
            if not changed:  # a custom executor proposed nothing applicable
                break
        async with self._unit() as u:
            project = await u.tx.get_project(project_id)
            if project is None or project.state not in (ProjectState.EXECUTING, ProjectState.INGESTING):
                return
            run = project.current_run
            tasks = [t for t in await u.tx.list_tasks(project_id=project_id) if t.run == run and not t.replaced]
            outcome = self.executor.outcome(tasks)
            if project.state == ProjectState.INGESTING and outcome != ProjectState.FAILED:
                return      # still understanding the request; only a failure settles it (the plan moves it on)
            if outcome is not None:
                counts: dict[str, int] = {}
                for t in tasks:
                    counts[t.state.value] = counts.get(t.state.value, 0) + 1
                await self._move_project(u, project, outcome, runs=self._settled_runs(project, outcome, self._now()),
                                         data={"task_states": counts, "run": run})

    @staticmethod
    def _settled_runs(project: ProjectRecord, outcome: ProjectState, now: datetime) -> list[RunRecord]:
        if not project.runs:
            return []
        last = project.runs[-1]
        if last.outcome is not None:
            return list(project.runs)
        return [*project.runs[:-1], last.model_copy(update={"outcome": outcome, "finished_at": now})]

    async def _assign_ready(self) -> None:
        async with self._assign_lock:
            ready = assignment_order(await self.store.list_tasks(states={S.READY}))
            if not ready:
                return
            load = agent_load(await self.store.list_executions(statuses=IN_FLIGHT_EXECUTIONS))
            for task in ready:
                agent = choose_agent(await self.registry.find_candidates(task.capability), load, task.rejected_by)
                if agent is None:
                    continue  # stays READY; retried on the next tick / registration / heartbeat
                try:
                    if await self._assign(task, agent.agent_id):
                        load[agent.agent_id] += 1
                except StoreError as exc:
                    log.info("assignment of %s lost a race: %s", task.task_id, exc)

    async def _assign(self, task: TaskRecord, agent_id: str) -> bool:
        with telemetry.span(f"manager.assign {task.capability}", trace_id=telemetry.task_trace_id(task.task_id),
                            attrs={"hmap.task_id": task.task_id, "hmap.capability": task.capability,
                                   "hmap.agent_id": agent_id, "hmap.attempt": task.attempts + 1,
                                   "hmap.replays": task.replays}) as span:
            return await self._assign_traced(task, agent_id, span.traceparent()
                                             or telemetry.task_traceparent(task.task_id))

    @staticmethod
    def _refine_flag(task: TaskRecord, project: ProjectRecord | None) -> bool:
        """``inputs["refine"]`` (a bool) overrides the project setting for one task (plan D3)."""
        override = task.inputs.get("refine")
        if isinstance(override, bool):
            return override
        return bool(project.refine) if project is not None else False

    async def _assign_traced(self, task: TaskRecord, agent_id: str, traceparent: str) -> bool:
        now = self._now()
        async with self._unit() as u:
            t = await u.tx.get_task(task.task_id)
            if t is None or t.state != S.READY or t.state_version != task.state_version:
                return False
            attempt = t.attempts + 1
            execution_id = new_execution_id()
            for prev in await u.tx.list_executions(task_id=t.task_id):
                if prev.superseded_by is None and prev.status in {
                        ExecutionStatus.PENDING, ExecutionStatus.ACTIVE, ExecutionStatus.FAILED,
                        ExecutionStatus.TIMED_OUT, ExecutionStatus.SUPERSEDED}:
                    await self._save_execution(u, prev, status=ExecutionStatus.SUPERSEDED, superseded_by=execution_id)
            await u.tx.insert_execution(ExecutionRecord(
                execution_id=execution_id, task_id=t.task_id, attempt=attempt, agent_id=agent_id,
                lease_until=now + timedelta(seconds=self.config.ack_timeout_s), created_at=now, updated_at=now))
            refs, upstream = await self._dependency_artifacts(u.tx, t)
            project = await u.tx.get_project(t.project_id)
            assign = TaskAssign(
                task_id=t.task_id, execution_id=execution_id, capability=t.capability, objective=t.objective,
                acceptance_criteria=t.acceptance_criteria, context_refs=t.context_refs, project_id=t.project_id,
                artifact_refs=[*t.artifact_refs, *refs], inputs={**t.inputs, "dependency_artifacts": upstream},
                dependencies=t.depends_on, priority=t.priority,
                cloud_ok=project.cloud_ok if project is not None else True, refine=self._refine_flag(t, project))
            env = make_envelope(assign, sender=self.config.manager_id, receiver=agent_id,
                                correlation_id=t.project_id, task_id=t.task_id, execution_id=execution_id,
                                project_id=t.project_id, traceparent=traceparent)
            await u.tx.add_command(t.capability, env)
            await self._move(u, t, S.ASSIGNED, active_execution_id=execution_id, attempts=attempt,
                             data={"agent_id": agent_id, "attempt": attempt, "execution_id": execution_id})
        return True

    @staticmethod
    async def _dependency_artifacts(tx: TaskStoreTx,
                                    task: TaskRecord) -> tuple[list[ArtifactRef], dict[str, list[str]]]:
        """Result artifacts of completed dependencies, handed to the dependant with its assignment."""
        refs: list[ArtifactRef] = []
        upstream: dict[str, list[str]] = {}
        for dep_id in task.depends_on:
            done = await tx.list_executions(task_id=dep_id, statuses={ExecutionStatus.SUCCEEDED})
            if not done:
                continue
            latest = max(done, key=lambda e: e.attempt)
            refs.extend(latest.result_refs)
            upstream[dep_id] = [r.artifact_id for r in latest.result_refs]
        return refs, upstream

"""Graph executor strategy (Sprint 1 item 1.13). Decides which tasks of a project may start, which are blocked, and
when the project is finished. Member 3 replaces it through the ``executor`` strategy slot of a ``Plugin``.

The executor is pure: it looks at task records and returns decisions; the Manager applies them (with CAS +
events). Approval gating is expressed by ``TaskRecord.needs_approval``.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from hmap.core.contracts import ProjectState, TaskGraph, TaskState
from hmap.manager.records import TaskRecord

# A dependant of a task in one of these states can never run.
DEAD_END_STATES: frozenset[TaskState] = frozenset(
    {TaskState.FAILED, TaskState.DEAD_LETTERED, TaskState.CANCELLED, TaskState.BLOCKED})
FAILURE_STATES: frozenset[TaskState] = frozenset({TaskState.FAILED, TaskState.DEAD_LETTERED, TaskState.CANCELLED})
SETTLED_STATES: frozenset[TaskState] = FAILURE_STATES | {TaskState.COMPLETED, TaskState.BLOCKED}


@runtime_checkable
class GraphExecutor(Protocol):
    def order(self, graph: TaskGraph) -> list[str]:
        """Plan task ids in creation order (dependencies first)."""

    def ready(self, tasks: Sequence[TaskRecord]) -> list[str]:
        """CREATED task ids that may become READY now."""

    def blocked(self, tasks: Sequence[TaskRecord]) -> dict[str, list[str]]:
        """CREATED task id -> dependency ids that make it unrunnable (task becomes BLOCKED)."""

    def outcome(self, tasks: Sequence[TaskRecord]) -> ProjectState | None:
        """COMPLETED / FAILED when the project's graph is settled, else None (keep executing)."""


class NaiveTopologicalExecutor:
    """Kahn-style: a task is ready when it is CREATED, approved, and every dependency is COMPLETED. Dependants of
    FAILED / DEAD_LETTERED / CANCELLED (and, transitively, BLOCKED) tasks are BLOCKED."""

    def order(self, graph: TaskGraph) -> list[str]:
        remaining = {t.id: set(t.depends_on) for t in graph.tasks}
        out: list[str] = []
        while remaining:
            layer = [tid for t in graph.tasks if (tid := t.id) in remaining and not remaining[tid]]
            if not layer:  # unreachable: TaskGraph validates acyclicity
                raise ValueError("dependency cycle")
            for tid in layer:
                del remaining[tid]
                out.append(tid)
            for deps in remaining.values():
                deps.difference_update(layer)
        return out

    def ready(self, tasks: Sequence[TaskRecord]) -> list[str]:
        by_id = {t.task_id: t for t in tasks}
        return [t.task_id for t in tasks
                if t.state == TaskState.CREATED and not t.needs_approval
                and all(d in by_id and by_id[d].state == TaskState.COMPLETED for d in t.depends_on)]

    def blocked(self, tasks: Sequence[TaskRecord]) -> dict[str, list[str]]:
        state = {t.task_id: t.state for t in tasks}
        out: dict[str, list[str]] = {}
        changed = True
        while changed:  # propagate transitively within one pass
            changed = False
            for t in tasks:
                if t.task_id in out or state[t.task_id] != TaskState.CREATED:
                    continue
                bad = [d for d in t.depends_on if state.get(d) in DEAD_END_STATES]
                if bad:
                    out[t.task_id] = bad
                    state[t.task_id] = TaskState.BLOCKED
                    changed = True
        return out

    def outcome(self, tasks: Sequence[TaskRecord]) -> ProjectState | None:
        if not tasks:
            return None
        if all(t.state == TaskState.COMPLETED for t in tasks):
            return ProjectState.COMPLETED
        if all(t.state in SETTLED_STATES for t in tasks) and any(t.state in FAILURE_STATES for t in tasks):
            return ProjectState.FAILED
        return None

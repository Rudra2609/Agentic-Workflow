"""Layer-parallel DAG executor (spec item 3.9), plugged into the Manager's ``executor`` strategy slot. Without the
planning plug-in the Manager keeps Member 1's naive executor.

Same semantics as the naive executor (a task is ready when it is approved and every dependency is COMPLETED;
dependants of failed / cancelled / blocked tasks are BLOCKED, transitively; the project settles when every task
has), plus:

- **order**: tasks are created layer by layer (topological generations), the most urgent first inside a layer;
- **concurrency cap**: at most ``HMAP_PLAN_MAX_PARALLEL`` plan steps of one project are in flight at once
  (READY .. REVIEWING); the rest wait in CREATED and start as slots free up, most urgent (critical path) first.
  Non-plan tasks (extraction, planning, replanning) are never held back.

Pure: it looks at task records and returns decisions; the Manager applies them.
"""

from collections.abc import Sequence

from hmap.core.config import Settings
from hmap.core.contracts import Priority, TaskGraph, TaskState
from hmap.manager.executor import NaiveTopologicalExecutor
from hmap.manager.records import TaskRecord

# a plan step in one of these states holds a slot
ACTIVE_STATES: frozenset[TaskState] = frozenset({
    TaskState.READY, TaskState.ASSIGNED, TaskState.ACCEPTED, TaskState.RUNNING, TaskState.RESULT_SUBMITTED,
    TaskState.REVIEWING, TaskState.NEEDS_REVISION, TaskState.RETRY_SCHEDULED})
_RANK = {Priority.URGENT: 0, Priority.HIGH: 1, Priority.NORMAL: 2, Priority.LOW: 3}


class LayerParallelExecutor(NaiveTopologicalExecutor):
    def __init__(self, max_parallel: int | None = None) -> None:
        self._max_parallel = max_parallel

    @property
    def max_parallel(self) -> int:
        if self._max_parallel is None:
            try:
                self._max_parallel = Settings.from_env().plan_max_parallel
            except ValueError:
                self._max_parallel = 4
        return max(1, self._max_parallel)

    def order(self, graph: TaskGraph) -> list[str]:
        remaining = {t.id: set(t.depends_on) for t in graph.tasks}
        by_id = {t.id: t for t in graph.tasks}
        out: list[str] = []
        while remaining:
            layer = sorted((tid for tid, deps in remaining.items() if not deps),
                           key=lambda tid: (_RANK.get(by_id[tid].priority, 2), tid))
            if not layer:  # unreachable: TaskGraph validates acyclicity
                raise ValueError("dependency cycle")
            for tid in layer:
                del remaining[tid]
            out.extend(layer)
            for deps in remaining.values():
                deps.difference_update(layer)
        return out

    def ready(self, tasks: Sequence[TaskRecord]) -> list[str]:
        candidates = super().ready(tasks)
        if not candidates:
            return []
        by_id = {t.task_id: t for t in tasks}
        free = [c for c in candidates if by_id[c].plan_task_id is None]  # pipeline steps: never capped
        plan = [c for c in candidates if by_id[c].plan_task_id is not None]
        out = list(free)
        # the cap is per project (one reconcile call sees one project, but be safe with several)
        projects = {by_id[c].project_id for c in plan}
        for project_id in sorted(projects):
            active = sum(1 for t in tasks if t.project_id == project_id and t.plan_task_id is not None
                         and t.state in ACTIVE_STATES)
            room = self.max_parallel - active
            if room <= 0:
                continue
            mine = sorted((c for c in plan if by_id[c].project_id == project_id),
                          key=lambda c: (_RANK.get(by_id[c].priority, 2), by_id[c].created_at, c))
            out.extend(mine[:room])
        return out

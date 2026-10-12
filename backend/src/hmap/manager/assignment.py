"""Agent selection for READY tasks (research §20, §27). Pure functions; the Manager applies the result."""

from collections import Counter
from collections.abc import Collection, Iterable, Sequence

from hmap.core.contracts import ExecutionStatus, Priority
from hmap.manager.records import ExecutionRecord, TaskRecord
from hmap.services.registry.base import AgentRecord

IN_FLIGHT_EXECUTIONS: frozenset[ExecutionStatus] = frozenset({ExecutionStatus.PENDING, ExecutionStatus.ACTIVE})
_PRIORITY_RANK = {Priority.URGENT: 0, Priority.HIGH: 1, Priority.NORMAL: 2, Priority.LOW: 3}


def assignment_order(tasks: Iterable[TaskRecord]) -> list[TaskRecord]:
    """Highest priority first, then oldest."""
    return sorted(tasks, key=lambda t: (_PRIORITY_RANK.get(t.priority, 2), t.created_at, t.task_id))


def agent_load(executions: Iterable[ExecutionRecord]) -> Counter[str]:
    """In-flight executions per agent according to the task store (authoritative, unlike heartbeats)."""
    return Counter(e.agent_id for e in executions if e.agent_id and e.status in IN_FLIGHT_EXECUTIONS)


def free_slots(agent: AgentRecord, load: Counter[str]) -> int:
    """Conservative: what the agent last advertised, but never more than ``max_slots`` minus what we assigned to it
    (covers assignments made since its last heartbeat)."""
    return min(agent.available_slots, agent.max_slots - load.get(agent.agent_id, 0))


def choose_agent(candidates: Sequence[AgentRecord], load: Counter[str],
                 rejected_by: Collection[str] = ()) -> AgentRecord | None:
    """Keep the registry's order (real before stubs, least loaded) but drop agents without a free slot and try
    agents that already rejected this task last."""
    usable = [c for c in candidates if free_slots(c, load) > 0]
    usable.sort(key=lambda c: c.agent_id in rejected_by)  # stable
    return usable[0] if usable else None

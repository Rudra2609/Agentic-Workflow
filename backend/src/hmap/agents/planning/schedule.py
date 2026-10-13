"""Scheduling (spec item 3.5): parallel layers, the critical path, slack and priorities. Deterministic: ties are
broken by task id, so the same plan always gives the same schedule.

Priorities (D10): a step takes the highest MoSCoW priority of its requirements (must -> high, should -> normal,
could -> low; spine steps normal), and steps on the critical path go up one level (at most urgent), so the
Manager's assignment order (priority first) works the critical path first.
"""

import networkx as nx

from hmap.agents.planning.model import Schedule, WorkingPlan
from hmap.agents.planning.validate import graph_of
from hmap.core.contracts import Priority
from hmap.core.contracts.domain import PlanTask, RequirementSet

_UP = {Priority.LOW: Priority.NORMAL, Priority.NORMAL: Priority.HIGH, Priority.HIGH: Priority.URGENT,
       Priority.URGENT: Priority.URGENT}
DEFAULT_EFFORT = 1.0
_MOSCOW = {"must": Priority.HIGH, "should": Priority.NORMAL, "could": Priority.LOW}
_ORDER = [Priority.LOW, Priority.NORMAL, Priority.HIGH, Priority.URGENT]


def _effort(t: PlanTask) -> float:
    return t.est_effort if t.est_effort is not None else DEFAULT_EFFORT


def compute(tasks: list[PlanTask]) -> Schedule:
    g = graph_of(tasks)
    if not nx.is_directed_acyclic_graph(g):
        raise ValueError("cannot schedule a plan with a dependency cycle")
    by_id = {t.id: t for t in tasks}
    layers = [sorted(layer) for layer in nx.topological_generations(g)]
    order = [n for layer in layers for n in layer]
    earliest: dict[str, float] = {}
    for n in order:
        earliest[n] = max((earliest[p] + _effort(by_id[p]) for p in g.predecessors(n)), default=0.0)
    finish = {n: earliest[n] + _effort(by_id[n]) for n in order}
    makespan = max(finish.values(), default=0.0)
    latest_finish: dict[str, float] = {}
    for n in reversed(order):
        latest_finish[n] = min((latest_finish[s] - _effort(by_id[s]) for s in g.successors(n)), default=makespan)
    slack = {n: round(latest_finish[n] - finish[n], 3) for n in order}
    # the critical path: from a zero-slack start, always the zero-slack successor with the smallest id
    critical: list[str] = []
    current = next((n for n in order if slack[n] <= 1e-9 and g.in_degree(n) == 0), None)
    while current is not None:
        critical.append(current)
        current = next((s for s in sorted(g.successors(current))
                        if slack[s] <= 1e-9 and abs(earliest[s] - finish[current]) <= 1e-9), None)
    return Schedule(layers=layers, critical_path=critical, earliest_start={n: round(earliest[n], 3) for n in order},
                    slack=slack, total_effort=round(sum(_effort(t) for t in tasks), 1), makespan=round(makespan, 1))


def apply_priorities(plan: WorkingPlan, schedule: Schedule, rs: RequirementSet) -> None:
    """Always derived from the requirements and the schedule (never accumulated over versions)."""
    critical = set(schedule.critical_path)
    moscow = {r.id: _MOSCOW[r.priority] for r in rs.requirements}
    for t in list(plan.tasks):
        found = [moscow[r] for r in t.requirement_ids if r in moscow]
        base = max(found, key=lambda p: _ORDER.index(p)) if found else Priority.NORMAL
        new = _UP[base] if t.id in critical else base
        if new != t.priority:
            plan.replace(t.model_copy(update={"priority": new}))


def execution_order(tasks: list[PlanTask]) -> list[str]:
    """Layer by layer; inside a layer the most urgent first, then by id (what the executor creates first)."""
    rank = {Priority.URGENT: 0, Priority.HIGH: 1, Priority.NORMAL: 2, Priority.LOW: 3}
    by_id = {t.id: t for t in tasks}
    g = graph_of(tasks)
    return [n for layer in nx.topological_generations(g)
            for n in sorted(layer, key=lambda x: (rank.get(by_id[x].priority, 2), x))]

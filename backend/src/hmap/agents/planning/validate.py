"""Plan validation and auto-repair (spec item 3.4). The model proposes, this code decides.

``check`` / ``validate_plan`` only report (a stable function: Member 4 uses it as a programmatic critic, Sprint 4
item 4.10). ``repair`` fixes what can be fixed mechanically and logs every change; whatever is left is reported.

A valid plan: unique ids, known dependencies, acyclic, exactly one sink (the final review), every task reachable
from it, capabilities from the whitelist and fitting the phase, acceptance criteria on every task, requirement ids
that exist, and every requirement covered by a build / test / document step or explicitly flagged.
"""

from collections.abc import Iterable

import networkx as nx

from hmap.agents.planning.model import PHASE_RANK, EdgeSource, Issue, WorkingPlan
from hmap.agents.planning.templates import PHASE_ALLOWED, PHASE_CAPABILITY, PLAN_CAPABILITIES, SPINE, SPINE_IDS
from hmap.core.contracts import Priority
from hmap.core.contracts.capabilities import REVIEW_FINAL
from hmap.core.contracts.domain import PlanTask, RequirementSet, TaskGraph

MAX_TASKS = 40
WORK_PHASES = frozenset({"implement", "test", "document"})
# cycle breaking drops the least trusted dependency first
_TRUST: dict[str, int] = {"llm": 0, "repair": 1, "human": 2, "rule": 3, "dataflow": 4, "template": 5}


def graph_of(tasks: Iterable[PlanTask]) -> "nx.DiGraph[str]":
    g: nx.DiGraph[str] = nx.DiGraph()
    tasks = list(tasks)
    g.add_nodes_from(t.id for t in tasks)
    known = set(g.nodes)
    for t in tasks:
        for d in t.depends_on:
            if d in known and d != t.id:
                g.add_edge(d, t.id)
    return g


def coverage_of(tasks: Iterable[PlanTask]) -> set[str]:
    return {r for t in tasks if t.phase in WORK_PHASES for r in t.requirement_ids}


def check(tasks: list[PlanTask], rs: RequirementSet | None = None, *, flagged: Iterable[str] = (),
          allowed: Iterable[str] = PLAN_CAPABILITIES, max_tasks: int = MAX_TASKS) -> list[Issue]:
    issues: list[Issue] = []
    allowed = frozenset(allowed)
    ids = [t.id for t in tasks]
    known = set(ids)
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(Issue(code="duplicate_id", message=f"two tasks share the id {dup}", task_id=dup))
    if not tasks:
        return [Issue(code="empty", message="the plan has no tasks")]
    req_ids = {r.id for r in rs.requirements} if rs is not None else None
    titles: dict[str, str] = {}
    for t in tasks:
        if not t.title.strip():
            issues.append(Issue(code="empty_title", message=f"{t.id} has no title", task_id=t.id))
        for d in t.depends_on:
            if d == t.id:
                issues.append(Issue(code="self_dependency", message=f"{t.id} depends on itself", task_id=t.id))
            elif d not in known:
                issues.append(Issue(code="unknown_dependency", message=f"{t.id} depends on unknown {d}", task_id=t.id))
        if t.agent_capability not in allowed:
            issues.append(Issue(code="unknown_capability", task_id=t.id,
                                message=f"{t.id} uses {t.agent_capability!r}, which no agent in the plan provides"))
        elif t.agent_capability not in PHASE_ALLOWED[t.phase]:
            issues.append(Issue(code="capability_phase", severity="warning", task_id=t.id,
                                message=f"{t.id}: {t.agent_capability} is unusual in the {t.phase} phase"))
        if not [c for c in t.acceptance_criteria if c.strip()]:
            issues.append(Issue(code="no_acceptance", task_id=t.id, message=f"{t.id} has no acceptance criteria"))
        if req_ids is not None:
            for r in t.requirement_ids:
                if r not in req_ids:
                    issues.append(Issue(code="unknown_requirement", task_id=t.id, requirement_id=r,
                                        message=f"{t.id} refers to {r}, which is not in the requirements"))
        if t.phase in ("implement", "test") and not t.requirement_ids and t.id not in SPINE_IDS:
            issues.append(Issue(code="unjustified", severity="warning", task_id=t.id,
                                message=f"{t.id} ({t.title}) serves no requirement"))
        key = t.title.strip().lower()
        if key in titles:
            issues.append(Issue(code="duplicate_title", severity="warning", task_id=t.id,
                                message=f"{t.id} has the same title as {titles[key]}"))
        titles.setdefault(key, t.id)
    g = graph_of(tasks)
    try:
        cycle = nx.find_cycle(g)
        issues.append(Issue(code="cycle", message="dependency cycle: " + " -> ".join(e[0] for e in cycle)
                            + f" -> {cycle[0][0]}", task_id=cycle[0][0]))
    except nx.NetworkXNoCycle:
        sinks = [n for n in g.nodes if g.out_degree(n) == 0]
        review = [t.id for t in tasks if t.agent_capability == REVIEW_FINAL]
        if len(sinks) != 1:
            issues.append(Issue(code="multiple_sinks", message=f"the plan should end in one final review; it ends "
                                f"in {len(sinks)} tasks: {', '.join(sorted(sinks)[:6])}"))
        elif not review or sinks[0] not in review:
            issues.append(Issue(code="sink_not_review", task_id=sinks[0],
                                message=f"the plan ends in {sinks[0]}, not in a final review"))
    for t in tasks:
        if not t.depends_on and t.phase not in ("research",):
            issues.append(Issue(code="orphan", severity="warning", task_id=t.id,
                                message=f"{t.id} ({t.title}) has no predecessor; it would start at once"))
    if rs is not None:
        covered = coverage_of(tasks) | set(flagged)
        for req in rs.requirements:
            if req.id not in covered:
                issues.append(Issue(code="uncovered", requirement_id=req.id,
                                    message=f"{req.id} is not covered by any build, test or document step"))
    if len(tasks) > max_tasks:
        issues.append(Issue(code="too_many_tasks", severity="warning",
                            message=f"{len(tasks)} tasks (limit {max_tasks})"))
    return issues


def validate_plan(graph: TaskGraph, rs: RequirementSet | None = None, *, flagged: Iterable[str] = (),
                  allowed: Iterable[str] = PLAN_CAPABILITIES) -> list[Issue]:
    """Public critic (Member 4): every problem of a finished ``TaskGraph`` (errors and warnings)."""
    return check(list(graph.tasks), rs, flagged=flagged, allowed=allowed)


def errors(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


# ------------------------------------------------------------------ repair


def repair(plan: WorkingPlan, rs: RequirementSet | None = None, *, kind: str = "software",
           allowed: Iterable[str] = PLAN_CAPABILITIES, max_tasks: int = MAX_TASKS,
           frozen: Iterable[str] = ()) -> WorkingPlan:
    """Fix ``plan`` in place (and return it). Never removes a task; only edges, fields and merges of tiny steps.
    ``frozen`` tasks (finished or running, during a replan) are never merged away."""
    allowed = frozenset(allowed)
    _unique_ids(plan)
    known = plan.ids()
    req_ids = {r.id for r in rs.requirements} if rs is not None else None
    by_req = {r.id: r for r in rs.requirements} if rs is not None else {}
    for t in list(plan.tasks):
        changes: dict[str, object] = {}
        deps = [d for d in dict.fromkeys(t.depends_on) if d in known and d != t.id]
        if deps != t.depends_on:
            changes["depends_on"] = deps
            plan.repairs.append(f"{t.id}: removed unknown or repeated dependencies")
        cap = t.agent_capability
        if cap not in allowed or cap not in PHASE_ALLOWED[t.phase]:
            new = PHASE_CAPABILITY[kind][t.phase]
            if new not in allowed:
                new = next((c for c in PHASE_ALLOWED[t.phase] if c in allowed), new)
            if new != cap:
                changes["agent_capability"] = new
                plan.repairs.append(f"{t.id}: capability {cap!r} -> {new}")
        if req_ids is not None:
            reqs = [r for r in dict.fromkeys(t.requirement_ids) if r in req_ids]
            if reqs != t.requirement_ids:
                changes["requirement_ids"] = reqs
                plan.repairs.append(f"{t.id}: dropped unknown requirement ids")
        if not [c for c in t.acceptance_criteria if c.strip()]:
            reqs = list(changes.get("requirement_ids", t.requirement_ids))  # type: ignore[call-overload]
            changes["acceptance_criteria"] = ([f"{r}: {by_req[r].text}" for r in reqs if r in by_req][:4]
                                              or [f"{t.title} is done and checked"])
            plan.repairs.append(f"{t.id}: added acceptance criteria from its requirements")
        if not t.title.strip():
            changes["title"] = f"Step {t.id}"
        if changes:
            plan.replace(t.model_copy(update=changes))
        if (dep_set := changes.get("depends_on")) is not None:
            for d in t.depends_on:
                if d not in dep_set:  # type: ignore[operator]
                    plan.edge_source.pop((d, t.id), None)
    _break_cycles(plan)
    _dedupe_titles(plan)
    _limit_size(plan, max_tasks, frozenset(frozen))
    _attach_orphans(plan)
    _single_sink(plan, kind)
    return plan


def _unique_ids(plan: WorkingPlan) -> None:
    seen: set[str] = set()
    for i, t in enumerate(plan.tasks):
        if t.id in seen:
            n = 2
            while f"{t.id}-{n}" in seen:
                n += 1
            plan.tasks[i] = t.model_copy(update={"id": f"{t.id}-{n}"})
            plan.repairs.append(f"renamed a second {t.id} to {t.id}-{n}")
        seen.add(plan.tasks[i].id)


def _edge_rank(plan: WorkingPlan, edge: tuple[str, str]) -> tuple[int, int, str]:
    by_id = {t.id: t for t in plan.tasks}
    source: EdgeSource | str = plan.edge_source.get(edge, "llm")
    a, b = by_id[edge[0]], by_id[edge[1]]
    backward = 0 if PHASE_RANK[a.phase] > PHASE_RANK[b.phase] else 1
    return (_TRUST.get(source, 0), backward, f"{edge[0]}>{edge[1]}")


def _break_cycles(plan: WorkingPlan) -> None:
    for _ in range(10_000):
        try:
            cycle = nx.find_cycle(graph_of(plan.tasks))
        except nx.NetworkXNoCycle:
            return
        edges = [(str(e[0]), str(e[1])) for e in cycle]
        weakest = min(edges, key=lambda e: _edge_rank(plan, e))
        source = plan.edge_source.get(weakest, "llm")
        plan.remove_edge(*weakest)
        plan.repairs.append(f"broke a dependency cycle by removing {weakest[1]} -> {weakest[0]} ({source})")


def _dedupe_titles(plan: WorkingPlan) -> None:
    seen: dict[str, int] = {}
    for t in list(plan.tasks):
        key = t.title.strip().lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            plan.replace(t.model_copy(update={"title": f"{t.title.strip()} ({seen[key]})"}))


def _limit_size(plan: WorkingPlan, max_tasks: int, frozen: frozenset[str] = frozenset()) -> None:
    """Over the limit: merge test steps of the same group, then build steps of the same group (pairwise)."""
    for phase in ("test", "implement"):
        while len(plan.tasks) > max_tasks:
            groups: dict[str, list[PlanTask]] = {}
            for t in plan.tasks:
                if t.phase == phase and t.id not in SPINE_IDS and t.id not in frozen:
                    groups.setdefault(plan.task_group.get(t.id, ""), []).append(t)
            pair = next(((g[0], g[1]) for g in sorted(groups.values(), key=len, reverse=True) if len(g) > 1), None)
            if pair is None:
                break
            _merge(plan, *pair)


def _merge(plan: WorkingPlan, keep: PlanTask, drop: PlanTask) -> None:
    merged = keep.model_copy(update={
        "title": keep.title if len(keep.title) > 60 else f"{keep.title} + {drop.title}"[:120],
        "description": " ".join(x for x in (keep.description, drop.description) if x),
        "requirement_ids": list(dict.fromkeys([*keep.requirement_ids, *drop.requirement_ids])),
        "acceptance_criteria": list(dict.fromkeys([*keep.acceptance_criteria, *drop.acceptance_criteria]))[:8],
        "depends_on": [d for d in dict.fromkeys([*keep.depends_on, *drop.depends_on]) if d not in (keep.id, drop.id)],
        "est_effort": round((keep.est_effort or 0) + (drop.est_effort or 0), 1) or None,
        "priority": max((keep.priority, drop.priority), key=lambda p: list(Priority).index(p)),
        "research_questions": list(dict.fromkeys([*keep.research_questions, *drop.research_questions])),
    })
    plan.tasks = [t for t in plan.tasks if t.id != drop.id]
    plan.replace(merged)
    for i, t in enumerate(plan.tasks):
        if drop.id in t.depends_on:
            deps = [keep.id if d == drop.id else d for d in t.depends_on]
            plan.tasks[i] = t.model_copy(update={"depends_on": [d for d in dict.fromkeys(deps) if d != t.id]})
    for (a, b), s in list(plan.edge_source.items()):
        if drop.id in (a, b):
            plan.edge_source.pop((a, b))
            na, nb = (keep.id if a == drop.id else a), (keep.id if b == drop.id else b)
            if na != nb:
                plan.edge_source.setdefault((na, nb), s)
    plan.task_group.pop(drop.id, None)
    plan.repairs.append(f"merged {drop.id} into {keep.id} to keep the plan within its size limit")
    _break_cycles(plan)


def _attach_orphans(plan: WorkingPlan) -> None:
    """A step with no predecessor starts at once; outside research that is a missing dependency: attach it to its
    phase's predecessor (build -> design, test -> build steps it checks, document -> tests)."""
    by_id = {t.id: t for t in plan.tasks}
    for t in list(plan.tasks):
        if t.depends_on or t.phase == "research":
            continue
        anchors: list[str] = []
        if t.id == "design" or t.phase == "design":
            anchors = [x for x in ["verify", "research"] if x in by_id][:1]
        elif t.phase == "implement":
            anchors = [x for x in ["design"] if x in by_id]
        elif t.phase == "test":
            reqs = set(t.requirement_ids)
            anchors = [b.id for b in plan.tasks if b.phase == "implement" and reqs & set(b.requirement_ids)] or \
                [b.id for b in plan.tasks if b.phase == "implement"]
        elif t.phase == "document":
            anchors = [b.id for b in plan.tasks if b.phase == "test"] or \
                [b.id for b in plan.tasks if b.phase == "implement"]
        elif t.phase == "review":
            continue
        for a in anchors:
            if a != t.id and _would_not_cycle(plan, a, t.id):
                plan.add_edge(a, t.id, "repair")
        if anchors:
            plan.repairs.append(f"{t.id} had no predecessor: now after {', '.join(anchors[:4])}"
                                + ("…" if len(anchors) > 4 else ""))


def _would_not_cycle(plan: WorkingPlan, before: str, after: str) -> bool:
    g = graph_of(plan.tasks)
    return not (after in g and before in g and nx.has_path(g, after, before))


def _single_sink(plan: WorkingPlan, kind: str) -> None:
    reviews = [t for t in plan.tasks if t.agent_capability == REVIEW_FINAL]
    if not reviews:
        step = next(s for s in SPINE[kind] if s.id == "review")
        rid = "review" if "review" not in plan.ids() else "final-review"
        plan.tasks.append(PlanTask(id=rid, title=step.title, description=step.description,
                                   agent_capability=REVIEW_FINAL, phase="review",
                                   acceptance_criteria=list(step.acceptance), est_effort=step.effort))
        plan.task_group[rid] = "g-review"
        plan.repairs.append("the plan had no final review: added one")
        reviews = [plan.tasks[-1]]
    sink = reviews[-1]
    g = graph_of(plan.tasks)
    for other in reviews[:-1]:  # several reviews: the last one is the end, the others feed it
        if not nx.has_path(g, sink.id, other.id):
            plan.add_edge(other.id, sink.id, "repair")
    g = graph_of(plan.tasks)
    ends = [n for n in g.nodes if g.out_degree(n) == 0 and n != sink.id]
    for n in sorted(ends):  # the review comes after everything else
        if not nx.has_path(g, sink.id, n):
            plan.add_edge(n, sink.id, "template")


def reduce(plan: WorkingPlan) -> None:
    """Transitive reduction: drop A->C when A->B->C exists, so the drawn plan stays readable. Meaning unchanged."""
    g = graph_of(plan.tasks)
    if not nx.is_directed_acyclic_graph(g):
        return
    keep = set(nx.transitive_reduction(g).edges())
    for t in list(plan.tasks):
        deps = [d for d in t.depends_on if (d, t.id) in keep]
        if deps != t.depends_on:
            for d in t.depends_on:
                if d not in deps:
                    plan.edge_source.pop((d, t.id), None)
            plan.replace(t.model_copy(update={"depends_on": deps}))

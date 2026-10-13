"""Roadmap (spec item 3.7): the plan's hierarchy (phase -> part -> feature group, ``Phase.parent_id``), milestones,
effort and the critical path, as JSON for the UI and Markdown for people."""

import re

from hmap.agents.planning.model import PHASES, Schedule, WorkingPlan
from hmap.agents.planning.skeleton import PHASE_NAMES, phase_group_id
from hmap.core.contracts.domain import Milestone, Phase, PlanTask, RequirementSet, Roadmap

MAX_CHILDREN = 8   # spec 3.2 branching limit: a group shows at most this many steps directly
MAX_DEPTH = 3


def limit_width(plan: WorkingPlan, order: list[str]) -> None:
    """A group with more than ``MAX_CHILDREN`` direct steps is split into sub-groups of at most that many (in
    execution order), as long as the hierarchy stays ``MAX_DEPTH`` levels deep; deeper groups keep their steps."""
    parents = {g[0]: g[2] for g in plan.groups}

    def depth(gid: str) -> int:
        d = 1
        while parents.get(gid) is not None and d < 10:
            gid, d = parents[gid], d + 1  # type: ignore[assignment]
        return d

    rank = {tid: i for i, tid in enumerate(order)}
    for gid, name, _parent in list(plan.groups):
        members = sorted((t for t, g in plan.task_group.items() if g == gid), key=lambda t: rank.get(t, 1 << 30))
        if len(members) <= MAX_CHILDREN or depth(gid) >= MAX_DEPTH:
            continue
        for k in range(0, len(members), MAX_CHILDREN):
            sub = f"{gid}-{k // MAX_CHILDREN + 1}"
            plan.groups.append((sub, f"{name} ({k // MAX_CHILDREN + 1})", gid))
            parents[sub] = gid
            for tid in members[k:k + MAX_CHILDREN]:
                plan.task_group[tid] = sub


def build(plan: WorkingPlan, schedule: Schedule, rs: RequirementSet, *, flagged: dict[str, str],
          questions: list[str]) -> Roadmap:
    ids = plan.ids()
    phases: list[Phase] = []
    for gid, name, parent in plan.groups:
        members = [t.id for t in plan.tasks if plan.task_group.get(t.id) == gid]
        phases.append(Phase(id=gid, name=name, task_ids=members, parent_id=parent))
    # drop empty groups (no tasks and no non-empty children), keeping the order
    def has_tasks(gid: str) -> bool:
        return any(p.task_ids for p in phases if p.id == gid) or any(has_tasks(p.id) for p in phases
                                                                     if p.parent_id == gid)
    phases = [p for p in phases if has_tasks(p.id)]
    return Roadmap(phases=phases, milestones=_milestones(plan, ids),
                   markdown=markdown(plan.tasks, phases, schedule, rs, flagged=flagged, questions=questions))


def _milestones(plan: WorkingPlan, ids: set[str]) -> list[Milestone]:
    out: list[Milestone] = []
    research = [t.id for t in plan.tasks if t.phase == "research"]
    if research:
        out.append(Milestone(name="Research checked", task_ids=research))
    if "design" in ids:
        out.append(Milestone(name="Design ready", task_ids=["design"]))
    parts = [(gid, name) for gid, name, parent in plan.groups if parent == phase_group_id("implement")
             and re.fullmatch(r"g-implement-p\d+", gid)]
    if parts:
        for gid, name in parts:
            pid = gid.split("-")[-1]
            members = [t.id for t in plan.tasks if t.phase in ("implement", "test")
                       and plan.task_group.get(t.id, "").split("-")[2:3] == [pid]]
            if members:
                out.append(Milestone(name=f"{name} built and tested", task_ids=members))
    else:
        members = [t.id for t in plan.tasks if t.phase in ("implement", "test")]
        if members:
            out.append(Milestone(name="Built and tested", task_ids=members))
    docs = [t.id for t in plan.tasks if t.phase == "document"]
    if docs:
        out.append(Milestone(name="Documents ready", task_ids=docs))
    reviews = [t.id for t in plan.tasks if t.phase == "review"]
    if reviews:
        out.append(Milestone(name="Ready to hand in", task_ids=reviews))
    return out


def markdown(tasks: list[PlanTask], phases: list[Phase], schedule: Schedule, rs: RequirementSet, *,
             flagged: dict[str, str], questions: list[str]) -> str:
    by_id = {t.id: t for t in tasks}
    critical = set(schedule.critical_path)
    lines = ["# Plan", "",
             f"{len(tasks)} steps, about {schedule.total_effort:g} hours of work; with enough agents working in "
             f"parallel the longest chain (critical path) takes {schedule.makespan:g} hours over "
             f"{len(schedule.layers)} stages.", ""]
    for phase in PHASES:
        top = next((p for p in phases if p.id == phase_group_id(phase)), None)
        if top is None:
            continue
        lines += [f"## {PHASE_NAMES[phase]}", ""]
        lines += _group_lines(top, phases, by_id, critical, depth=0)
        lines.append("")
    lines += ["## Critical path", "", " -> ".join(f"{t} ({by_id[t].title})" for t in schedule.critical_path)
              or "(none)", ""]
    lines += ["## Stages (steps in one stage can run at the same time)", ""]
    lines += [f"{i}. " + ", ".join(layer) for i, layer in enumerate(schedule.layers, start=1)]
    if flagged:
        lines += ["", "## Not given to an agent", ""]
        lines += [f"- {rid}: {reason}" for rid, reason in flagged.items()]
    if questions:
        lines += ["", "## Questions before approving", ""]
        lines += [f"- {q}" for q in questions]
    uncovered = [r.id for r in rs.requirements if r.id not in flagged
                 and not any(r.id in t.requirement_ids for t in tasks if t.phase not in ("review",))]
    if uncovered:
        lines += ["", "## Requirements without a step", "", ", ".join(uncovered)]
    return "\n".join(lines).rstrip() + "\n"


def _group_lines(group: Phase, phases: list[Phase], by_id: dict[str, PlanTask], critical: set[str], *,
                 depth: int) -> list[str]:
    pad = "  " * depth
    out: list[str] = []
    for tid in group.task_ids:
        t = by_id[tid]
        mark = " **(critical)**" if tid in critical else ""
        reqs = f" [{', '.join(t.requirement_ids)}]" if t.requirement_ids else ""
        after = f" — after {', '.join(t.depends_on)}" if t.depends_on else ""
        effort = f", {t.est_effort:g} h" if t.est_effort is not None else ""
        out.append(f"{pad}- **{tid}** {t.title} ({t.agent_capability}{effort}, {t.priority.value}){reqs}{after}{mark}")
    for child in (p for p in phases if p.parent_id == group.id):
        out.append(f"{pad}- *{child.name}*")
        out += _group_lines(child, phases, by_id, critical, depth=depth + 1)
    return out

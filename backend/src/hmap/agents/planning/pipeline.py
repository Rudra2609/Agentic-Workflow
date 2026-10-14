"""The planning pipeline (spec §4):

    RequirementSet -> skeleton (template spine, parts) -> decomposition per part (model, or rules)
      -> coverage fill-in + deliverables -> dependencies -> validation + repair -> transitive reduction
      -> schedule (layers, critical path, priorities) -> coverage matrix -> roadmap -> TaskGraph + PlanReport

``finalize`` (repair .. report) is shared with human edits and replanning, so every plan version passes the same
checks.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from hmap.agents.planning import dependencies, roadmap, schedule
from hmap.agents.planning.coverage import coverage
from hmap.agents.planning.decompose import (
    DraftPlan,
    IdAllocator,
    ResultCache,
    add_deliverables,
    add_part,
    batches,
    decompose_batch,
    ensure_part_coverage,
    rule_draft,
)
from hmap.agents.planning.model import PHASES, PROMPT_VERSION, PlanReport, WorkingPlan
from hmap.agents.planning.skeleton import (
    PHASE_NAMES,
    Part,
    build_parts,
    build_skeleton,
    human_only,
    phase_group_id,
    review_questions,
    rule_research_questions,
    section_map,
)
from hmap.agents.planning.templates import PLAN_CAPABILITIES
from hmap.agents.planning.validate import MAX_TASKS, check, reduce, repair
from hmap.core.contracts.domain import RequirementSet, TaskGraph
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.planning")

ProgressFn = Callable[[int, str], Awaitable[None]]


@dataclass
class PlanResult:
    graph: TaskGraph
    report: PlanReport
    kind: str


async def _noop(_p: int, _s: str) -> None:
    return None


async def make_plan(rs: RequirementSet, llm: LLMClient | None, *, document_model: dict[str, Any] | None = None,
                    capabilities: Iterable[str] | None = None, cache: ResultCache | None = None,
                    progress: ProgressFn | None = None, check_cancelled: Callable[[], None] | None = None,
                    use_llm: bool = True, max_tasks: int = MAX_TASKS, version: int = 1,
                    requirement_set_ref: dict[str, str | int] | None = None) -> PlanResult:
    progress = progress or _noop
    allowed = frozenset(c for c in (capabilities or PLAN_CAPABILITIES) if c in PLAN_CAPABILITIES) or \
        frozenset(PLAN_CAPABILITIES)
    plan, kind = build_skeleton(rs)
    plan.flagged.update(human_only(rs))
    questions, low = review_questions(rs)
    plan.questions.extend(questions)
    parts = build_parts(rs, section_map(document_model))
    multi = len(parts) > 1
    ids = IdAllocator()
    report = PlanReport(graph_version=version, project_kind=kind, prompt_version=PROMPT_VERSION,
                        requirement_set=requirement_set_ref, low_confidence=low)
    research_qs: list[str] = []
    part_tasks: dict[str, list[str]] = {}
    total = sum(len(batches([r for r in p.requirements if r.id not in plan.flagged])) for p in parts) or 1
    done = 0
    for part in parts:
        reqs = [r for r in part.requirements if r.id not in plan.flagged]
        part_tasks[part.id] = []
        for batch in batches(reqs):
            if check_cancelled:
                check_cancelled()
            done += 1
            await progress(5 + int(70 * (done - 1) / total), f"Planning {part.label} ({done} of {total})")
            if not batch:
                continue
            draft, source = await _draft(llm if use_llm else None, part, batch, rs, kind, cache, report)
            for item in draft.not_plannable:
                if item.requirement_id in {r.id for r in batch}:
                    plan.flagged[item.requirement_id] = item.reason.strip() or "the model says no agent can do it"
            research_qs += [q.strip() for q in draft.research_questions if q and q.strip()]
            plan.questions += [q.strip() for q in draft.open_questions if q and q.strip()]
            part_tasks[part.id] += add_part(plan, part, draft, rs, kind, ids, multi_part=multi, allowed=allowed,
                                            source=source)
        ensure_part_coverage(plan, part, part_tasks[part.id], rs, kind, ids, multi_part=multi, allowed=allowed)
    report.method = "rules" if report.llm_calls == 0 else ("mixed" if report.fallbacks else "llm")
    # research seeds for Member 5: the model's questions, else rule-made ones
    research_qs = list(dict.fromkeys(research_qs))[:6] or rule_research_questions(rs, parts, kind)
    research = plan.task("research")
    if research is not None:
        plan.replace(research.model_copy(update={"research_questions": research_qs}))
    await progress(80, "Linking the steps")
    report.deliverables = add_deliverables(plan, rs, kind, ids, allowed)
    dependencies.infer(plan, parts, part_tasks)
    graph, report = finalize(plan, rs, kind=kind, report=report, allowed=allowed, max_tasks=max_tasks,
                             version=version)
    await progress(95, f"Plan ready: {len(graph.tasks)} steps")
    return PlanResult(graph=graph, report=report, kind=kind)


async def _draft(llm: LLMClient | None, part: Part, batch: list[Any], rs: RequirementSet, kind: str,
                 cache: ResultCache | None, report: PlanReport) -> tuple[DraftPlan, Any]:
    if llm is None:
        return rule_draft(part, batch, kind), "rules"
    try:
        draft, answered_by = await decompose_batch(llm, part, batch, rs, kind, cache)
    except Cancelled:
        raise
    except Exception as exc:  # the model failed or answered garbage: the rules still give a plan
        log.warning("planning model failed; rules used", part=part.label, error=type(exc).__name__)
        report.fallbacks.append(f"{part.label}: {type(exc).__name__}")
        return rule_draft(part, batch, kind), "rules"
    report.llm_calls += 1
    report.answered_by[answered_by] = report.answered_by.get(answered_by, 0) + 1
    if not draft.steps:
        report.fallbacks.append(f"{part.label}: empty answer")
        return rule_draft(part, batch, kind), "rules"
    return draft, "llm"


def finalize(plan: WorkingPlan, rs: RequirementSet, *, kind: str, report: PlanReport,
             allowed: Iterable[str] = PLAN_CAPABILITIES, max_tasks: int = MAX_TASKS,
             version: int = 1, do_repair: bool = True,
             frozen: Iterable[str] = ()) -> tuple[TaskGraph, PlanReport]:
    """Validate (+ repair), reduce, schedule, cover and describe ``plan``; build the ``TaskGraph`` (version
    ``version``) and fill ``report``. Raises ``ValueError`` when errors remain (only possible without repair)."""
    if do_repair:
        repair(plan, rs, kind=kind, allowed=allowed, max_tasks=max_tasks, frozen=frozen)
    issues = check(plan.tasks, rs, flagged=plan.flagged, allowed=allowed, max_tasks=max_tasks)
    hard = [i for i in issues if i.severity == "error" and i.code != "uncovered"]
    if hard:
        raise ValueError("; ".join(i.message for i in hard[:5]))
    reduce(plan)
    _ensure_groups(plan)
    sched = schedule.compute(plan.tasks)
    schedule.apply_priorities(plan, sched, rs)
    order = schedule.execution_order(plan.tasks)
    by_id = {t.id: t for t in plan.tasks}
    tasks = [by_id[i] for i in order]
    cov = coverage(tasks, rs, plan.flagged)
    for rid in cov.uncovered:  # repair adds coverage for every part, so this only happens after human edits
        plan.questions.append(f"{rid} is not covered by any step")
    roadmap.limit_width(plan, order)
    rm = roadmap.build(plan, sched, rs, flagged=cov.flagged, questions=list(dict.fromkeys(plan.questions)))
    graph = TaskGraph(project_id=rs.project_id, version=version, tasks=tasks, roadmap=rm,
                      coverage_matrix=cov.matrix)
    counts: dict[str, int] = {}
    for t in tasks:
        for d in t.depends_on:
            src = plan.edge_source.get((d, t.id), "human")
            counts[src] = counts.get(src, 0) + 1
    report = report.model_copy(update={
        "graph_version": version, "repairs": list(dict.fromkeys(plan.repairs)),
        "issues": [i for i in check(tasks, rs, flagged=plan.flagged, allowed=allowed, max_tasks=max_tasks)
                   if i.severity == "warning" or i.code == "uncovered"],
        "flagged": dict(cov.flagged), "questions": list(dict.fromkeys(plan.questions)), "edges": counts,
        "schedule": sched})
    return graph, report


def _ensure_groups(plan: WorkingPlan) -> None:
    """Every task sits in a group of its phase (a human edit may add tasks or move them to another phase)."""
    known = {g[0]: g for g in plan.groups}
    for phase in PHASES:
        if phase_group_id(phase) not in known:
            plan.groups.append((phase_group_id(phase), PHASE_NAMES[phase], None))
    order = {phase_group_id(p): i for i, p in enumerate(PHASES)}
    plan.groups.sort(key=lambda g: order.get(_top(plan, g[0]), 99))
    for t in plan.tasks:
        gid = plan.task_group.get(t.id)
        if gid is None or gid not in {g[0] for g in plan.groups} or _top(plan, gid) != phase_group_id(t.phase):
            plan.task_group[t.id] = phase_group_id(t.phase)


def _top(plan: WorkingPlan, gid: str) -> str:
    parents = {g[0]: g[2] for g in plan.groups}
    for _ in range(10):
        parent = parents.get(gid)
        if parent is None:
            return gid
        gid = parent
    return gid


def working_plan_from(graph: TaskGraph) -> WorkingPlan:
    """A stored plan back into a ``WorkingPlan`` (edits and replans): groups from the roadmap, edges as ``human``."""
    plan = WorkingPlan(tasks=list(graph.tasks))
    for p in graph.roadmap.phases:
        plan.groups.append((p.id, p.name, p.parent_id))
        for tid in p.task_ids:
            plan.task_group[tid] = p.id
    for t in graph.tasks:
        for d in t.depends_on:
            plan.edge_source[(d, t.id)] = "human"
    return plan

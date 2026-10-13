"""Replanning and human edits (spec items 3.10, 3.12).

**Replan** — a new version of the current plan after human feedback ("don't use X"), failed steps, or changed
requirements. Finished and running steps are *frozen*: they keep their id and content, so the Manager keeps their
records and results (``Manager.replace_graph``). Only the rest changes:

- requirements that were added get new steps (rules or the model); removed ones are dropped from unfinished
  steps, and unfinished build / test steps left without any requirement are removed;
- failed (or blocked) steps keep their id and run again, with a note;
- feedback goes to the model, which may remove, change or add unfinished steps (never frozen ones); without a
  model the feedback becomes an acceptance criterion of every unfinished build step ("Do not use X").

**Edit** — a person's version of the plan: refused (422) on hard errors (cycle, unknown capability or dependency,
duplicate id), otherwise repaired like a generated plan (missing criteria, loose ends -> final review) and re-scheduled.
"""

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, field_validator

from hmap.agents.planning.decompose import (
    DraftPlan,
    DraftStep,
    IdAllocator,
    ResultCache,
    add_part,
    ensure_part_coverage,
    rule_draft,
)
from hmap.agents.planning.model import PROMPT_VERSION, Issue, PlanReport, WorkingPlan
from hmap.agents.planning.pipeline import PlanResult, finalize, working_plan_from
from hmap.agents.planning.skeleton import Part, review_questions, short
from hmap.agents.planning.templates import PHASE_ALLOWED, PLAN_CAPABILITIES
from hmap.agents.planning.validate import WORK_PHASES, check, errors
from hmap.core.contracts.domain import PlanTask, RequirementSet, TaskGraph
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient, Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.planning.replan")

# Manager task states whose work must be preserved (finished, or an agent is on it)
FROZEN_STATES = frozenset({"COMPLETED", "ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_SUBMITTED", "REVIEWING",
                           "NEEDS_REVISION", "RETRY_SCHEDULED"})
FAILED_STATES = frozenset({"FAILED", "DEAD_LETTERED", "BLOCKED", "CANCELLED"})
_AVOID = re.compile(r"\b(?:do not|don't|dont|never|stop) (?:use|using)\s+(.+?)(?:[.;,!]|$)|\b(?:avoid|without)\s+"
                    r"(?:using\s+)?(.+?)(?:[.;,!]|$)", re.I)


class TaskChange(BaseModel):
    id: str
    title: str | None = None
    description: str | None = None
    acceptance_criteria: list[str] | None = None


class ReplanDraft(BaseModel):
    remove: list[str] = Field(default_factory=list, description="ids of unfinished steps to drop")
    change: list[TaskChange] = Field(default_factory=list)
    add: list[DraftStep] = Field(default_factory=list)
    notes: str = ""

    @field_validator("remove", "change", "add", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("notes", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value


REPLAN_PROMPT = """You revise a project plan after feedback from the person who owns it. Some steps are finished
or running: never remove or change them. Change only the unfinished steps.

Return JSON with:
- remove: ids of unfinished steps that the feedback makes unnecessary or wrong.
- change: unfinished steps to adjust ({"id", and any of "title", "description", "acceptance_criteria"}).
- add: new steps, in the same format as before: key (n1, n2, ...), title, description, phase ("implement" or
  "test"), requirement_ids (only ids from the list), acceptance_criteria, effort_hours, depends_on (keys of other new
  steps, or ids of existing steps), group.
- notes: one sentence on what you changed.

Keep every requirement covered by some step. Do the smallest change that follows the feedback. Never invent
requirements."""


def _plan_lines(graph: TaskGraph, frozen: set[str]) -> list[str]:
    lines = []
    for t in graph.tasks:
        state = "FINISHED/RUNNING - do not touch" if t.id in frozen else "unfinished"
        reqs = ", ".join(t.requirement_ids) or "-"
        lines.append(f"{t.id} [{t.phase}, {state}] {t.title} (requirements: {reqs}; after: "
                     f"{', '.join(t.depends_on) or '-'})")
    return lines


async def _ask(llm: LLMClient, graph: TaskGraph, rs: RequirementSet, feedback: str, frozen: set[str],
               cache: ResultCache | None) -> tuple[ReplanDraft, str]:
    user = "\n".join(["Feedback: " + feedback.strip(), "", "Requirements:",
                      *[f"{r.id} [{r.priority}] {r.text}" for r in rs.requirements], "", "Current plan:",
                      *_plan_lines(graph, frozen)])
    messages = [Message(role="system", content=REPLAN_PROMPT), Message(role="user", content=user)]
    key = "replan-" + hashlib.sha256(f"{PROMPT_VERSION}\x00{user}".encode()).hexdigest()[:40]
    if cache is not None and (hit := await cache.get(key)) is not None:
        return ReplanDraft.model_validate_json(hit), "memory"
    resp = await llm.generate("reasoner", messages, schema=ReplanDraft, temperature=0.0, max_tokens=3000, seed=7)
    draft: ReplanDraft = resp.parsed
    if cache is not None:
        await cache.put(key, draft.model_dump_json())
    return draft, f"{resp.usage.provider or 'unknown'}:{resp.usage.model or 'unknown'}"


async def replan(current: TaskGraph, rs: RequirementSet, *, states: dict[str, str], feedback: str | None = None,
                 failed: Iterable[str] = (), llm: LLMClient | None = None, kind: str = "software",
                 cache: ResultCache | None = None, previous: PlanReport | None = None,
                 allowed: Iterable[str] = PLAN_CAPABILITIES) -> PlanResult:
    allowed = frozenset(allowed)
    frozen = {pid for pid, s in states.items() if s in FROZEN_STATES and pid in {t.id for t in current.tasks}}
    plan = working_plan_from(current)
    plan.flagged = dict(previous.flagged) if previous else {}
    report = PlanReport(graph_version=current.version + 1, origin="replanned", project_kind=kind,
                        prompt_version=PROMPT_VERSION, feedback=(feedback or "").strip() or None,
                        requirement_set=previous.requirement_set if previous else None)
    questions, low = review_questions(rs)
    plan.questions = questions
    report.low_confidence = low
    req_ids = {r.id for r in rs.requirements}
    ids = IdAllocator(next_number=1 + max((int(m.group(1)) for t in current.tasks
                                           if (m := re.fullmatch(r"T(\d+)", t.id))), default=0))
    whole = Part("p1", "", list(rs.requirements))

    # 1. requirements that disappeared or changed
    for t in list(plan.tasks):
        if t.id in frozen:
            continue
        keep = [r for r in t.requirement_ids if r in req_ids]
        if keep != t.requirement_ids:
            if not keep and t.phase in ("implement", "test"):
                _remove(plan, t.id)
                plan.repairs.append(f"removed {t.id} ({t.title}): its requirements no longer exist")
                continue
            plan.replace(t.model_copy(update={"requirement_ids": keep}))
    for rid in [r for r in plan.flagged if r not in req_ids]:
        plan.flagged.pop(rid)

    # 2. failed / blocked steps run again
    redo = [pid for pid in dict.fromkeys([*failed, *(p for p, s in states.items() if s in FAILED_STATES)])
            if pid not in frozen]
    for pid in redo:
        found = plan.task(pid)
        if found is not None and "previous attempt failed" not in found.description.lower():
            plan.replace(found.model_copy(update={"description": (found.description + " " if found.description else "")
                                              + "(Run again: the previous attempt failed or was blocked.)"}))

    # 3. the feedback
    if feedback and feedback.strip():
        draft = None
        if llm is not None:
            try:
                draft, answered = await _ask(llm, current, rs, feedback, frozen, cache)
                report.llm_calls += 1
                report.answered_by[answered] = 1
            except Cancelled:
                raise
            except Exception as exc:
                log.warning("replan model failed; rules used", error=type(exc).__name__)
                report.fallbacks.append(f"feedback: {type(exc).__name__}")
        if draft is not None:
            _apply_draft(plan, draft, whole, rs, kind, ids, frozen, allowed)
        else:
            _apply_rule_feedback(plan, feedback, frozen, whole, rs, kind, ids, allowed)

    # 4. every requirement covered again (new requirements, removed steps)
    open_ids = [t.id for t in plan.tasks if t.id not in frozen]
    covered = {r for t in plan.tasks if t.phase in WORK_PHASES for r in t.requirement_ids}
    missing = [r for r in rs.requirements if r.id not in covered and r.id not in plan.flagged]
    if missing:
        made = add_part(plan, whole, rule_draft(whole, missing, kind), rs, kind, ids, multi_part=False,
                        allowed=allowed, source="rules")
        plan.repairs.append(f"new steps {', '.join(made)} for {', '.join(r.id for r in missing)}")
        ensure_part_coverage(plan, Part("p1", "", missing), made, rs, kind, ids, multi_part=False, allowed=allowed)
        open_ids += made
    # 5. new work after finished documents / final review: those run again (new ids, so the Manager re-creates them)
    _rerun_finishers(plan, current, frozen, states)
    report.method = "llm" if report.llm_calls else "rules"
    graph, report = finalize(plan, rs, kind=kind, report=report, allowed=allowed, version=current.version + 1,
                             frozen=frozen)
    return PlanResult(graph=graph, report=report, kind=kind)


def _remove(plan: WorkingPlan, tid: str) -> None:
    gone = plan.task(tid)
    if gone is None:
        return
    plan.tasks = [t for t in plan.tasks if t.id != tid]
    for i, t in enumerate(plan.tasks):  # dependants inherit the removed step's dependencies
        if tid in t.depends_on:
            deps = [d for d in t.depends_on if d != tid] + [d for d in gone.depends_on if d not in t.depends_on]
            plan.tasks[i] = t.model_copy(update={"depends_on": [d for d in dict.fromkeys(deps) if d != t.id]})
    plan.task_group.pop(tid, None)


def _apply_draft(plan: WorkingPlan, draft: ReplanDraft, whole: Part, rs: RequirementSet, kind: str,
                 ids: IdAllocator, frozen: set[str], allowed: frozenset[str]) -> None:
    for tid in draft.remove:
        if tid in frozen:
            plan.repairs.append(f"kept {tid}: it is finished or running")
        elif plan.task(tid) is not None and plan.task(tid).phase != "review":  # type: ignore[union-attr]
            _remove(plan, tid)
            plan.repairs.append(f"removed {tid} (feedback)")
    for ch in draft.change:
        t = plan.task(ch.id)
        if t is None or ch.id in frozen:
            continue
        update: dict[str, Any] = {}
        if ch.title and ch.title.strip():
            update["title"] = short(ch.title, 120)
        if ch.description is not None:
            update["description"] = ch.description.strip()
        if ch.acceptance_criteria:
            update["acceptance_criteria"] = [c for c in ch.acceptance_criteria if c.strip()][:8] or \
                t.acceptance_criteria
        if update:
            plan.replace(t.model_copy(update=update))
            plan.repairs.append(f"changed {ch.id} (feedback)")
    if draft.add:
        existing = plan.ids()
        added = DraftPlan(steps=[s.model_copy(update={"depends_on": [d for d in s.depends_on if d not in existing]})
                                 for s in draft.add])
        made = add_part(plan, whole, added, rs, kind, ids, multi_part=False, allowed=allowed, source="llm")
        key_to_id = dict(zip([s.key for s in draft.add if s.title.strip()], made, strict=False))
        for s in draft.add:
            new_id = key_to_id.get(s.key)
            for d in s.depends_on:
                if new_id and d in existing:
                    plan.add_edge(d, new_id, "llm")
        if made:
            plan.repairs.append(f"added {', '.join(made)} (feedback)")


def _apply_rule_feedback(plan: WorkingPlan, feedback: str, frozen: set[str], whole: Part, rs: RequirementSet,
                         kind: str, ids: IdAllocator, allowed: frozenset[str]) -> None:
    m = _AVOID.search(feedback)
    full = f"Follow this feedback: {feedback.strip()}"
    criterion = f"Do not use {(m.group(1) or m.group(2)).strip()}" if m else full
    added = [criterion] if criterion == full else [criterion, full]
    targets = [t for t in plan.tasks if t.id not in frozen and t.phase in ("design", "implement", "test")]
    for t in targets:
        new = [c for c in added if c not in t.acceptance_criteria]
        if new:
            plan.replace(t.model_copy(update={"acceptance_criteria": [*t.acceptance_criteria, *new]}))
    if any(t.phase == "implement" for t in targets):
        plan.repairs.append(f"added \"{criterion}\" to every unfinished design, build and test step")
        return
    # every build step is finished or running: the feedback becomes a change request on the finished work
    builds = [t for t in plan.tasks if t.phase == "implement"]
    reqs = sorted({r for t in builds for r in t.requirement_ids}, key=lambda r: (len(r), r))
    change = DraftPlan(steps=[
        DraftStep(key="c1", title=short(f"Change request: {feedback.strip()}", 110), phase="implement",
                  description=f"Rework the finished code to follow the feedback: {feedback.strip()}",
                  requirement_ids=reqs, acceptance_criteria=[*added, "everything that worked before still works"]),
        DraftStep(key="c2", title="Check the change request", phase="test", requirement_ids=reqs, depends_on=["c1"],
                  acceptance_criteria=[criterion, "all earlier checks pass again"])])
    made = add_part(plan, whole, change, rs, kind, ids, multi_part=False, allowed=allowed, source="rules")
    for b in builds:
        if made:
            plan.add_edge(b.id, made[0], "rule")
    plan.repairs.append(f"every build step had started: added change-request steps {', '.join(made)}")


def _rerun_finishers(plan: WorkingPlan, current: TaskGraph, frozen: set[str], states: dict[str, str]) -> None:
    """New steps after the documents / final review finished: give those finishers new ids, so they run again over
    the changed work instead of being kept as done."""
    old_ids = {t.id for t in current.tasks}
    if not any(t.id not in old_ids for t in plan.tasks):
        return
    version = current.version + 1
    for t in list(plan.tasks):
        if t.phase not in ("document", "review") or states.get(t.id) != "COMPLETED":
            continue
        new_id = f"{t.id.split('-v')[0]}-v{version}"
        plan.tasks = [x.model_copy(update={"id": new_id}) if x.id == t.id else
                      x.model_copy(update={"depends_on": [new_id if d == t.id else d for d in x.depends_on]})
                      for x in plan.tasks]
        if t.id in plan.task_group:
            plan.task_group[new_id] = plan.task_group.pop(t.id)
        for (a, b), src in list(plan.edge_source.items()):
            if t.id in (a, b):
                plan.edge_source.pop((a, b))
                plan.edge_source[(new_id if a == t.id else a, new_id if b == t.id else b)] = src
        frozen.discard(t.id)
        plan.repairs.append(f"{t.id} runs again as {new_id}: the work changed after it finished")


# ------------------------------------------------------------------ human edits


def apply_edit(edited: TaskGraph | dict[str, Any], rs: RequirementSet, *, base: TaskGraph, kind: str,
               states: dict[str, str] | None = None, author: str | None = None,
               previous: PlanReport | None = None) -> tuple[TaskGraph, PlanReport, list[Issue]]:
    """A person's plan -> the next version. Returns ``(graph, report, [])``, or ``(base, previous, errors)`` when the
    edit has problems the validator must not guess about."""
    raw = edited.model_dump(mode="json") if isinstance(edited, TaskGraph) else dict(edited)
    tasks = [PlanTask.model_validate(t) for t in raw.get("tasks") or []]
    hard = [i for i in errors(check(tasks, rs, flagged=(previous.flagged if previous else {})))
            if i.code in ("duplicate_id", "unknown_dependency", "self_dependency", "cycle", "unknown_capability",
                          "empty", "empty_title", "unknown_requirement")]
    frozen = {pid for pid, s in (states or {}).items() if s in FROZEN_STATES}
    base_by_id = {t.id: t for t in base.tasks}
    for pid in sorted(frozen):
        now = next((t for t in tasks if t.id == pid), None)
        if now is None:
            hard.append(Issue(code="frozen_removed", task_id=pid,
                              message=f"{pid} is finished or running and cannot be removed"))
        elif pid in base_by_id and _content(now) != _content(base_by_id[pid]):
            hard.append(Issue(code="frozen_changed", task_id=pid,
                              message=f"{pid} is finished or running and cannot be changed"))
    for t in tasks:
        if t.agent_capability in PLAN_CAPABILITIES and t.agent_capability not in PHASE_ALLOWED[t.phase] and \
                t.phase == "review":
            hard.append(Issue(code="capability_phase", task_id=t.id, message=f"{t.id}: the review phase needs "
                              "review.final"))
    if hard:
        return base, previous or PlanReport(), hard
    plan = working_plan_from(TaskGraph.model_construct(project_id=base.project_id, tasks=tasks, roadmap=base.roadmap))
    plan.flagged = dict(previous.flagged) if previous else {}
    questions, low = review_questions(rs)
    plan.questions = questions
    report = PlanReport(graph_version=base.version + 1, origin="edited", project_kind=kind,
                        prompt_version=PROMPT_VERSION, author=author, low_confidence=low,
                        requirement_set=previous.requirement_set if previous else None, method="rules")
    graph, report = finalize(plan, rs, kind=kind, report=report, version=base.version + 1, frozen=frozen)
    return graph, report, []


def _content(t: PlanTask) -> tuple[Any, ...]:
    return (t.title, t.agent_capability, tuple(t.requirement_ids), tuple(t.acceptance_criteria), t.phase)

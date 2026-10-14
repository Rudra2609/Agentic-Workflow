"""Refinement of Member 3's ``plan.generate`` result (Sprint 4 item 4.10). Member 3's folder is not edited: the
adapter runs through the runtime hook (plan D1) and calls Member 3's public functions only.

Critics (programmatic first):
- ``validity``     ``validate_plan`` (cycles, sinks, orphans, capabilities, criteria, unknown ids ...);
- ``coverage``     ``coverage``: every requirement is planned or flagged for a person;
- ``testability``  acceptance criteria that cannot be checked ("works properly");
- ``judge``        an LLM rubric: missing dependencies ("T3 -> T5": T5 needs T3's output), requirement work that is
                   not really planned, untestable criteria, duplicated or over-split steps.

Revisers:
- ``targeted``: the model proposes ``add_dependency`` / ``remove_dependency`` / ``add_criterion`` /
  ``replace_criterion`` on flagged steps; guards refuse unknown steps and cycles; the plan is rebuilt by Member 3's
  ``finalize`` (validation, repair, transitive reduction, schedule, roadmap, coverage) — so every refined plan passes
  the same checks as a planned one.
- ``full`` (Reflexion's strategy change): Member 3's ``replan(feedback=<the critique>)``, which may add, change or
  remove steps.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import networkx as nx
from pydantic import BaseModel, Field, field_validator

from hmap.agents.planning.agent import GRAPH_TYPE, REPORT_TYPE, report_id
from hmap.agents.planning.coverage import coverage
from hmap.agents.planning.model import PlanReport
from hmap.agents.planning.pipeline import finalize, working_plan_from
from hmap.agents.planning.replan import replan
from hmap.agents.planning.validate import graph_of, validate_plan
from hmap.agents.refine.core import Attempt, Critique, Issue, RefineContext, Revision, Strategy, digest
from hmap.agents.refine.critics import Criterion, LLMRubricCritic, ProgrammaticCritic, Rubric
from hmap.agents.refine.integration import RefineSetup
from hmap.agents.refine.revisers import reflection_lines
from hmap.agents.refine.stop import StopPolicy
from hmap.agents.refine.taxonomy import CODE_RULES
from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult
from hmap.core.contracts.domain import RequirementSet, TaskGraph
from hmap.core.errors import Cancelled
from hmap.core.llm.base import Message
from hmap.core.runtime.base import AgentContext
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.plan")

CRITICAL_CODES = frozenset({"cycle", "multiple_sinks", "sink_not_review", "empty", "duplicate_id"})
VAGUE_RE = re.compile(r"^\s*(?:it\s+)?(?:works?|done|completed?|finished|ok|good|correct(?:ly)?|properly|as expected|"
                      r"is implemented|implemented)\.?\s*$|\b(?:works properly|works well|as expected|"
                      r"looks good|is fine|etc)\b", re.I)


@dataclass
class PlanInput:
    requirements: RequirementSet
    report: PlanReport
    reports: dict[str, PlanReport] = field(default_factory=dict)   # graph digest -> its report (for the writer)

    @property
    def kind(self) -> str:
        return self.report.project_kind

    def report_for(self, graph: TaskGraph) -> PlanReport:
        return self.reports.get(digest(graph), self.report)


# ---------------------------------------------------------------------------------------------- critics


def check_validity(graph: TaskGraph, inp: PlanInput) -> list[Issue]:
    out: list[Issue] = []
    for i in validate_plan(graph, inp.requirements, flagged=inp.report_for(graph).flagged):
        if i.code == "uncovered":
            continue                                   # the coverage critic reports these
        severity = "critical" if i.code in CRITICAL_CODES else ("major" if i.severity == "error" else "minor")
        out.append(Issue(category=CODE_RULES.get(i.code, "LOGIC"), severity=severity,
                         description=i.message, location=i.task_id or i.requirement_id or "plan",
                         fix_hint=f"code {i.code}"))
    return out


def check_coverage(graph: TaskGraph, inp: PlanInput) -> list[Issue]:
    cov = coverage(list(graph.tasks), inp.requirements, inp.report_for(graph).flagged)
    by_id = {r.id: r for r in inp.requirements.requirements}
    return [Issue(category="REQUIREMENT_VIOLATION", severity="major", location=rid,
                  description=f"{rid} is not covered by any build, test or document step.",
                  evidence=by_id[rid].text[:200] if rid in by_id else None,
                  fix_hint="add a step for it or flag it for a person") for rid in cov.uncovered]


def check_testability(graph: TaskGraph, inp: PlanInput) -> list[Issue]:
    out = []
    for t in graph.tasks:
        vague = [c for c in t.acceptance_criteria if VAGUE_RE.search(c)]
        if vague and len(vague) == len([c for c in t.acceptance_criteria if c.strip()]):
            out.append(Issue(category="STYLE", severity="minor", location=t.id,
                             description=f"{t.id}'s acceptance criteria cannot be checked.", evidence=vague[0][:120],
                             fix_hint="state a concrete, checkable outcome"))
    return out[:5]


PLAN_RUBRIC = Rubric(
    name="plan", version="1", subject="a project plan: steps with dependencies, made from a list of requirements",
    criteria=(
        Criterion("P1", "Dependencies: does every step come after the steps whose results it needs? If a requirement "
                  "of step B uses something that a requirement of step A creates (a name, a command, a connection, "
                  "data, a schema, a part that is reused), B needs A. Name each missing dependency as 'A -> B' (A "
                  "must finish before B) and say what B needs from A.", 1.5, "LOGIC"),
        Criterion("P2", "Coverage: is each requirement's work done by build and test steps that really do it?", 1.0,
                  "REQUIREMENT_VIOLATION"),
        Criterion("P3", "Acceptance criteria: are they concrete and checkable?", 0.5, "STYLE"),
        Criterion("P4", "Granularity: no duplicated steps and no step split into trivial pieces?", 0.5, "STYLE"),
    ),
    instructions="The research, verify, design and review steps and the order research -> design -> build -> test "
                 "-> documents -> review come from a template and are correct. Steps listed as 'after: X' already "
                 "depend on X (directly); a dependency through other steps also counts.",
    location_hint="a step id (T3), a missing dependency written 'T3 -> T5', or a requirement id (R2)")


def render_plan(graph: TaskGraph, inp: PlanInput) -> str:
    req = "\n".join(f"{r.id} [{r.priority}] {r.text}" for r in inp.requirements.requirements)
    flagged = inp.report_for(graph).flagged
    steps = []
    for t in graph.tasks:
        crit = "; ".join(t.acceptance_criteria[:4])
        steps.append(f"{t.id} [{t.phase}] {t.title} (requirements: {', '.join(t.requirement_ids) or '-'}; after: "
                     f"{', '.join(t.depends_on) or '-'}) criteria: {crit or '-'}")
    out = f"Requirements:\n{req}\n\nPlan steps:\n" + "\n".join(steps)
    if flagged:
        out += "\n\nRequirements a person must do (not planned on purpose): " + ", ".join(sorted(flagged))
    return out


def _locations(graph: TaskGraph, inp: PlanInput) -> list[str]:
    return [t.id for t in graph.tasks] + [r.id for r in inp.requirements.requirements]


def plan_critics(*, judge: bool = True) -> list[Any]:
    critics: list[Any] = [
        ProgrammaticCritic(lambda g, i: check_validity(g, i), name="validity", covers={"SCHEMA"}),
        ProgrammaticCritic(lambda g, i: check_coverage(g, i), name="coverage", covers={"REQUIREMENT_VIOLATION"}),
        ProgrammaticCritic(lambda g, i: check_testability(g, i), name="testability", weight=0.5),
    ]
    if judge:
        critics.append(LLMRubricCritic(PLAN_RUBRIC, render=render_plan, locations=_locations, name="judge",
                                       weight=2.5))
    return critics


# ---------------------------------------------------------------------------------------------- revisers


class PlanChange(BaseModel):
    op: Literal["add_dependency", "remove_dependency", "add_criterion", "replace_criterion", "add_requirement"]
    before: str = Field(default="", description="for dependencies: the step that must finish first")
    after: str = Field(default="", description="for dependencies: the step that waits")
    task: str = Field(default="", description="for criteria and requirements: the step")
    requirement: str = Field(default="", description="for add_requirement: the requirement id (R3)")
    text: str = ""
    old_text: str = ""
    issue: int | None = None

    @field_validator("before", "after", "task", "requirement", "text", "old_text", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return "" if value is None else str(value)


class PlanChangeAnswer(BaseModel):
    changes: list[PlanChange] = Field(default_factory=list)
    notes: str = ""

    @field_validator("changes", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("notes", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value


PLAN_REVISE_PROMPT = """You correct a project plan using a reviewer's issues. Return {"changes": [...], "notes": "..."}
where each change is one of:
- {"op": "add_dependency", "before": "T3", "after": "T5", "issue": n}      (T5 must wait for T3)
- {"op": "remove_dependency", "before": "T3", "after": "T5", "issue": n}
- {"op": "add_criterion", "task": "T4", "text": "<a concrete, checkable acceptance criterion>", "issue": n}
- {"op": "replace_criterion", "task": "T4", "old_text": "<the current criterion>", "text": "<the better one>",
   "issue": n}
- {"op": "add_requirement", "task": "T1", "requirement": "R7", "issue": n}   (the build or test step T1 also does R7)
Fix only the listed issues, with the smallest change. Use only step ids from the plan. Never create a cycle. If an
issue is wrong, skip it and say so in notes."""

_IDS = re.compile(r"\b(?:[TR]\d+|research|verify|design|review(?:-v\d+)?)\b")


class PlanPatchReviser:
    """Targeted plan reviser: dependency and acceptance-criterion patches, rebuilt by Member 3's ``finalize``."""

    name = "plan-patch"

    def __init__(self, role: str | None = None, max_tokens: int = 2000) -> None:
        self.role = role
        self.max_tokens = max_tokens

    async def revise(self, output: TaskGraph, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: PlanInput | None = None, strategy: Strategy = "targeted") -> Revision:
        assert task_input is not None
        if not ctx.has_llm:
            return Revision(output=output, notes=["no model: nothing to change"], applied=0)
        issues = "\n".join(f"{n}. [{i.severity} {i.category}] at {i.location}: {i.description}"
                           + (f" (fix: {i.fix_hint[:160]})" if i.fix_hint else "")
                           for n, i in enumerate(critique.issues, start=1))
        parts = [f"Issues:\n{issues}"]
        if notes := reflection_lines(history, ctx):
            parts.append(f"Notes from earlier attempts:\n{notes}")
        parts.append(render_plan(output, task_input))
        msgs = [Message(role="system", content=PLAN_REVISE_PROMPT), Message(role="user", content="\n\n".join(parts))]
        answer: PlanChangeAnswer = await ctx.generate(self.role or ctx.reviser_role, msgs,  # type: ignore[arg-type]
                                                      schema=PlanChangeAnswer, max_tokens=self.max_tokens)
        # the steps an issue is about: its location, plus steps its description or fix hint names
        flagged = {m for i in critique.issues
                   for m in _IDS.findall(" ".join([i.location or "", i.description, i.fix_hint or ""]))}
        return apply_changes(output, answer, task_input, flagged, free=strategy != "targeted")


def apply_changes(graph: TaskGraph, answer: PlanChangeAnswer, inp: PlanInput, flagged: set[str], *,
                  free: bool = False) -> Revision:
    """Apply the guarded changes to a working copy and rebuild it with Member 3's ``finalize``."""
    plan = working_plan_from(graph)
    report = inp.report_for(graph)
    plan.flagged = dict(report.flagged)
    plan.questions = list(report.questions)
    ids = plan.ids()
    applied, rejected, notes = 0, [], []
    for ch in answer.changes[:20]:
        label = f"{ch.op} {ch.before or ch.task}{' -> ' + ch.after if ch.after else ''}"
        if ch.op in ("add_dependency", "remove_dependency"):
            a, b = ch.before.strip(), ch.after.strip()
            if a not in ids or b not in ids or a == b:
                rejected.append(f"{label}: unknown step")
                continue
            if not free and not ({a, b} & flagged):
                rejected.append(f"{label}: not flagged by an issue")
                continue
            g = graph_of(plan.tasks)
            if ch.op == "add_dependency":
                if nx.has_path(g, b, a):
                    rejected.append(f"{label}: would create a cycle")
                    continue
                if plan.add_edge(a, b, "llm"):
                    applied += 1
                    notes.append(f"{b} now waits for {a}")
            else:
                if not g.has_edge(a, b):
                    rejected.append(f"{label}: no such dependency")
                    continue
                plan.remove_edge(a, b)
                applied += 1
                notes.append(f"{b} no longer waits for {a}")
        elif ch.op == "add_requirement":
            tid, rid = ch.task.strip(), ch.requirement.strip()
            task = plan.task(tid)
            if task is None or rid not in {r.id for r in inp.requirements.requirements}:
                rejected.append(f"{label}: unknown step or requirement")
                continue
            if task.phase not in ("implement", "test", "document"):
                rejected.append(f"{label}: only build, test and document steps carry requirements")
                continue
            if not free and tid not in flagged and rid not in flagged:
                rejected.append(f"{label}: not flagged by an issue")
                continue
            if rid in task.requirement_ids:
                rejected.append(f"{label}: already there")
                continue
            plan.replace(task.model_copy(update={"requirement_ids": [*task.requirement_ids, rid]}))
            applied += 1
            notes.append(f"{tid} now also does {rid}")
        else:
            tid, text = ch.task.strip(), ch.text.strip()
            task = plan.task(tid)
            if task is None or not text or len(text) > 240:
                rejected.append(f"{label}: unknown step or empty criterion")
                continue
            if not free and tid not in flagged:
                rejected.append(f"{label}: not flagged by an issue")
                continue
            crit = list(task.acceptance_criteria)
            if ch.op == "replace_criterion":
                hit = next((i for i, c in enumerate(crit) if c.strip().casefold() == ch.old_text.strip().casefold()),
                           None)
                if hit is None:
                    rejected.append(f"{label}: criterion not found")
                    continue
                crit[hit] = text
            elif text.casefold() in {c.casefold() for c in crit}:
                rejected.append(f"{label}: already there")
                continue
            else:
                crit.append(text)
            plan.replace(task.model_copy(update={"acceptance_criteria": crit[:8]}))
            applied += 1
            notes.append(f"{tid}: criterion {'replaced' if ch.op == 'replace_criterion' else 'added'}")
    if answer.notes:
        notes.append(answer.notes[:300])
    if not applied:
        return Revision(output=graph, notes=notes, applied=0, rejected=rejected)
    try:
        new, new_report = finalize(plan, inp.requirements, kind=inp.kind, report=report, version=graph.version)
    except ValueError as exc:
        return Revision(output=graph, notes=notes, applied=0, rejected=[*rejected, f"plan invalid: {exc}"[:300]])
    inp.reports[digest(new)] = new_report
    return Revision(output=new, notes=notes, applied=applied, rejected=rejected)


class ReplanReviser:
    """``full`` strategy: Member 3's ``replan`` with the critique as feedback (may add / change / remove steps)."""

    name = "replan"

    async def revise(self, output: TaskGraph, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: PlanInput | None = None, strategy: Strategy = "full") -> Revision:
        assert task_input is not None
        lines = [f"{i.location}: {i.description}" + (f" ({i.fix_hint})" if i.fix_hint else "")
                 for i in critique.issues if i.severity in ("major", "critical")] or \
                [f"{i.location}: {i.description}" for i in critique.issues]
        notes = reflection_lines(history, ctx)
        feedback = ("Fix these problems found by a reviewer: " + " | ".join(lines))[:1500]
        if notes:
            feedback += (" Earlier attempts: " + notes.replace("\n", " "))[:500]
        report = task_input.report_for(output)
        try:
            result = await replan(output, task_input.requirements, states={}, feedback=feedback, llm=ctx.llm,
                                  kind=task_input.kind, previous=report)
        except Cancelled:
            raise
        except ValueError as exc:
            return Revision(output=output, applied=0, rejected=[f"replan refused: {exc}"[:300]])
        graph = result.graph.model_copy(update={"version": output.version, "project_id": output.project_id})
        task_input.reports[digest(graph)] = result.report.model_copy(update={"graph_version": output.version})
        return Revision(output=graph, notes=["replanned with the critique as feedback",
                                             *result.report.repairs[-3:]], applied=1)


def plan_reviser() -> Any:
    from hmap.agents.refine.revisers import StrategicReviser

    return StrategicReviser({"targeted": PlanPatchReviser(), "full": ReplanReviser()})


# ---------------------------------------------------------------------------------------------- setup


def plan_setup(inp: PlanInput, *, judge: bool = True, stop: StopPolicy | None = None,
               reflexion: bool = True) -> RefineSetup:
    async def write(graph: TaskGraph, ref: ArtifactRef, ctx: AgentContext) -> list[ArtifactRef]:
        latest = await ctx.artifacts.latest(ref.artifact_id, project_id=ctx.project_id)
        version = (latest.version if latest else ref.version) + 1
        g = graph.model_copy(update={"version": version, "project_id": ctx.project_id})
        new_ref = await ctx.put_json(g, artifact_type=GRAPH_TYPE, artifact_id=ref.artifact_id)
        report = inp.report_for(graph)
        report = report.model_copy(update={
            "graph_version": new_ref.version, "origin": "edited", "author": "refinement (automatic check)",
            "repairs": [*report.repairs, "checked and improved before approval (refinement)"]})
        report_ref = await ctx.put_json(report, artifact_type=REPORT_TYPE, artifact_id=report_id(ref.artifact_id))
        return [new_ref, report_ref]

    return RefineSetup(artifact_type=GRAPH_TYPE, load=TaskGraph.model_validate_json, critics=plan_critics(judge=judge),
                       reviser=plan_reviser(), stop=stop, task_input=inp, reflexion=reflexion,
                       memory_key="plan.generate", subject="plan", write=write)


async def build_setup(task: TaskAssign, result: TaskResult, ctx: AgentContext) -> RefineSetup | None:
    """``Plugin.refiners["plan.generate"]``: requirements from the task's inputs, the report from the result."""
    rs_ref = next((r for r in task.artifact_refs if r.artifact_type == "requirement-set"), None)
    report_ref = next((r for r in result.artifact_refs if r.artifact_type == REPORT_TYPE), None)
    if rs_ref is None or report_ref is None or not any(r.artifact_type == GRAPH_TYPE for r in result.artifact_refs):
        return None
    rs = await ctx.get_json(rs_ref, RequirementSet)
    report = await ctx.get_json(report_ref, PlanReport)
    return plan_setup(PlanInput(requirements=rs, report=report))

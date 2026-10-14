"""Decomposition (spec item 3.2): each part's requirements -> build and test steps.

One schema-constrained ``reasoner`` call per part, at most ``BATCH`` requirements per call (D14); the model never
sees or writes the spine, ids or capabilities outside the whitelist. A rule planner gives the same shape without a
model (no keys and no Ollama, or the model failed), so a plan always exists and says how it was made.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from hmap.agents.planning.model import PROMPT_VERSION, WorkingPlan
from hmap.agents.planning.skeleton import Part, phase_group_id, short
from hmap.agents.planning.templates import (
    DOC_DELIVERABLE,
    EFFORT,
    PHASE_ALLOWED,
    PHASE_CAPABILITY,
    PLAN_CAPABILITIES,
    clamp_effort,
)
from hmap.core.contracts import Priority
from hmap.core.contracts.domain import PlanTask, Requirement, RequirementSet
from hmap.core.llm.base import LLMClient, Message

BATCH = 15                 # requirements per model call
MAX_STEPS_PER_CALL = 12
RULE_GROUP = 3             # requirements per build step in the rule planner
TEMPERATURE = 0.0
SEED = 7
MAX_TOKENS = 4000
PRIORITY_OF = {"must": Priority.HIGH, "should": Priority.NORMAL, "could": Priority.LOW}
_RANK = {Priority.LOW: 0, Priority.NORMAL: 1, Priority.HIGH: 2, Priority.URGENT: 3}


class ResultCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def put(self, key: str, value: str) -> None: ...


class DraftStep(BaseModel):
    key: str = Field(description="short local name, e.g. b1, t1")
    title: str
    description: str = ""
    phase: Literal["implement", "test"] = "implement"
    capability: str = Field(default="", description="optional; one of the allowed capabilities")
    requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    effort_hours: float | None = None
    depends_on: list[str] = Field(default_factory=list, description="keys of steps in this answer")
    group: str = Field(default="", description="a short feature name shared by related steps")

    @field_validator("description", "capability", "group", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("requirement_ids", "acceptance_criteria", "depends_on", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value


class NotPlannable(BaseModel):
    requirement_id: str
    reason: str = ""


class DraftPlan(BaseModel):
    steps: list[DraftStep] = Field(default_factory=list)
    research_questions: list[str] = Field(default_factory=list)
    not_plannable: list[NotPlannable] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("steps", "research_questions", "not_plannable", "open_questions", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value


SYSTEM_PROMPT = """You plan the work for one part of a course assignment or project. A team of AI agents will carry
it out: a coding agent builds, a testing agent tests. Design, documentation and the final review are planned
separately, so do not add those steps.

Return JSON with "steps", "research_questions", "not_plannable" and "open_questions".

Each step:
- key: a short local name ("b1", "b2" for build steps, "t1", "t2" for test steps).
- title: an imperative title of at most 8 words ("Broadcast messages to all clients").
- description: one or two sentences on what to do.
- phase: "implement" (build something) or "test" (check that it works).
- requirement_ids: the ids of the requirements the step delivers or checks. Use only ids from the list.
- acceptance_criteria: 1-4 concrete, checkable statements taken from the requirements, keeping their numbers
  ("at least 10 clients connected at the same time").
- effort_hours: a rough estimate for one student (0.5 to 16).
- depends_on: keys of steps in your answer whose result this step needs (a test needs what it tests; the client
  may need the server's protocol). Never depend on a later step in a circle.
- group: a 1-3 word feature name shared by related steps ("Messaging").

Rules:
- Every requirement id in the list must appear in at least one step, unless it is in not_plannable.
- Use as few steps as the work needs: a build step covers 1-4 closely related requirements that one person would
  build together; a test step checks one feature group (it may check several build steps).
- Quality requirements (speed, robustness, usability) usually belong to test steps.
- Writing tests, scripts or documents that a requirement asks for is a build step.
- Dependencies: a step that uses, extends, tests or describes what another step makes depends on it (the command-line
  interface needs the logic it calls; unit tests need the code they test; code implementing a model needs the model).
- At most 12 steps. Never invent requirements, numbers, tools or extra features.
- research_questions: 2-5 specific questions the team must answer before designing (techniques, libraries the
  constraints allow, known pitfalls).
- not_plannable: requirements an AI agent cannot carry out (a live demo, handing in on a portal), with a reason.
- open_questions: anything unclear or contradictory (an empty list if nothing is)."""


def requirement_line(r: Requirement, section: str | None) -> str:
    where = f" (section: {section})" if section else ""
    return f"{r.id} [{r.priority}, {r.type.replace('_', '-')}] {r.text}{where}"


def build_messages(part: Part, batch: list[Requirement], rs: RequirementSet, kind: str) -> list[Message]:
    lines = [f"Project kind: {kind}.", f"Part: {part.label}." if part.name else "The whole request is one part.",
             "", "Requirements:"]
    lines += [requirement_line(r, part.sections.get(r.id)) for r in batch]
    if rs.constraints:
        lines += ["", "Constraints (respect them, do not make steps for them):"]
        lines += [f"{c.id} [{c.kind}] {c.text}" for c in rs.constraints]
    if kind == "document":
        lines += ["", "This is a writing project: build steps write sections, test steps check them."]
    return [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content="\n".join(lines))]


def _key(messages: list[Message]) -> str:
    h = hashlib.sha256(PROMPT_VERSION.encode())
    for m in messages:
        h.update(m.content.encode())
        h.update(b"\x00")
    return f"plan-{h.hexdigest()[:40]}"


async def decompose_batch(llm: LLMClient, part: Part, batch: list[Requirement], rs: RequirementSet, kind: str,
                          cache: ResultCache | None = None) -> tuple[DraftPlan, str]:
    """The model's draft for one batch and who answered (``provider:model``, or ``memory`` from the cache)."""
    messages = build_messages(part, batch, rs, kind)
    key = _key(messages)
    if cache is not None and (hit := await cache.get(key)) is not None:
        return DraftPlan.model_validate_json(hit), "memory"
    resp = await llm.generate("reasoner", messages, schema=DraftPlan, temperature=TEMPERATURE,
                              max_tokens=MAX_TOKENS, seed=SEED)
    draft: DraftPlan = resp.parsed
    if cache is not None:
        await cache.put(key, json.dumps(draft.model_dump(mode="json")))
    return draft, f"{resp.usage.provider or 'unknown'}:{resp.usage.model or 'unknown'}"


def batches(reqs: list[Requirement]) -> list[list[Requirement]]:
    return [reqs[i:i + BATCH] for i in range(0, len(reqs), BATCH)] or [[]]


# ------------------------------------------------------------------ rule planner


def rule_draft(part: Part, reqs: list[Requirement], kind: str) -> DraftPlan:
    """Without a model: requirements grouped by their section (else in runs of ``RULE_GROUP``), one build step per
    group of functional requirements and one test step per build step; quality requirements go to the tests."""
    functional = [r for r in reqs if r.type == "functional"] or list(reqs)
    quality = [r for r in reqs if r not in functional]
    groups: list[tuple[str, list[Requirement]]] = []
    for r in functional:
        section = part.sections.get(r.id, "")
        if groups and groups[-1][0] == section and len(groups[-1][1]) < RULE_GROUP:
            groups[-1][1].append(r)
        else:
            groups.append((section, [r]))
    steps: list[DraftStep] = []
    verb = "Write" if kind == "document" else "Implement"
    for i, (section, rs_) in enumerate(groups, start=1):
        title = f"{verb}: {short(rs_[0].text, 48)}" + (f" (+{len(rs_) - 1})" if len(rs_) > 1 else "")
        steps.append(DraftStep(
            key=f"b{i}", title=title, phase="implement", requirement_ids=[r.id for r in rs_],
            description="; ".join(r.text for r in rs_), acceptance_criteria=[f"{r.id}: {r.text}" for r in rs_],
            effort_hours=EFFORT["implement_per_requirement"] * len(rs_), group=section))
        steps.append(DraftStep(
            key=f"t{i}", title=f"Check: {short(rs_[0].text, 50)}" + (f" (+{len(rs_) - 1})" if len(rs_) > 1 else ""),
            phase="test", requirement_ids=[r.id for r in rs_], depends_on=[f"b{i}"],
            acceptance_criteria=[f"{r.id} works as stated" for r in rs_],
            effort_hours=EFFORT["test_base"] + EFFORT["test_per_requirement"] * len(rs_), group=section))
    if quality:
        steps.append(DraftStep(
            key="tq", title=f"Check quality of {part.label}", phase="test",
            requirement_ids=[r.id for r in quality], depends_on=[s.key for s in steps if s.phase == "implement"],
            acceptance_criteria=[f"{r.id}: {r.text}" for r in quality],
            effort_hours=EFFORT["test_base"] + EFFORT["test_per_requirement"] * len(quality), group="Quality"))
    return DraftPlan(steps=steps)


# ------------------------------------------------------------------ draft -> plan tasks


@dataclass
class IdAllocator:
    next_number: int = 1

    def new(self, taken: set[str]) -> str:
        while f"T{self.next_number}" in taken:
            self.next_number += 1
        tid = f"T{self.next_number}"
        self.next_number += 1
        return tid


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or "x"


def _priority(req_ids: list[str], by_id: dict[str, Requirement]) -> Priority:
    found = [PRIORITY_OF[by_id[r].priority] for r in req_ids if r in by_id]
    return max(found, key=lambda p: _RANK[p]) if found else Priority.NORMAL


def add_part(plan: WorkingPlan, part: Part, draft: DraftPlan, rs: RequirementSet, kind: str, ids: IdAllocator,
             *, multi_part: bool, allowed: frozenset[str], source: Literal["llm", "rules"]) -> list[str]:
    """Turn a draft into plan tasks in ``plan`` (ids T1.., groups, model edges). Returns the new task ids."""
    by_id = {r.id: r for r in rs.requirements}
    part_reqs = {r.id for r in part.requirements}
    key_to_id: dict[str, str] = {}
    new_ids: list[str] = []
    for step in draft.steps:
        if not step.title.strip() or step.key in key_to_id:
            continue
        phase = step.phase
        capability = step.capability if step.capability in PHASE_ALLOWED[phase] else PHASE_CAPABILITY[kind][phase]
        if capability not in allowed:
            capability = next((c for c in PLAN_CAPABILITIES if c in allowed and c in PHASE_ALLOWED[phase]),
                              PHASE_CAPABILITY[kind][phase])
        req_ids = [r for r in dict.fromkeys(step.requirement_ids) if r in part_reqs]
        criteria = [c.strip() for c in step.acceptance_criteria if c and c.strip()][:6]
        if not criteria:
            criteria = [f"{r}: {by_id[r].text}" for r in req_ids][:4] or [f"{step.title.strip()} is done and checked"]
        n = max(1, len(req_ids))
        default = (EFFORT["implement_per_requirement"] * n if phase == "implement"
                   else EFFORT["test_base"] + EFFORT["test_per_requirement"] * n)
        tid = ids.new(plan.ids())
        key_to_id[step.key] = tid
        title = step.title.strip()
        if multi_part and part.name and part.name.lower() not in title.lower():
            title = f"{part.name}: {title}"
        plan.tasks.append(PlanTask(
            id=tid, title=short(title, 120), description=step.description.strip(), agent_capability=capability,
            requirement_ids=req_ids, acceptance_criteria=criteria, phase=phase,
            priority=_priority(req_ids, by_id), est_effort=clamp_effort(step.effort_hours, default)))
        new_ids.append(tid)
        plan.task_group[tid] = _group_for(plan, part, phase, step.group, multi_part)
    for step in draft.steps:
        target = key_to_id.get(step.key)
        if target is None:
            continue
        for dep in step.depends_on:
            if dep in key_to_id and key_to_id[dep] != target:
                plan.add_edge(key_to_id[dep], target, "llm" if source == "llm" else "rule")
    return new_ids


def _group_for(plan: WorkingPlan, part: Part, phase: str, group: str, multi_part: bool) -> str:
    """phase -> part (several parts only) -> feature group: at most three levels (spec: depth <= 3)."""
    parent = phase_group_id(phase)
    if multi_part:
        pid = f"{parent}-{part.id}"
        if all(g[0] != pid for g in plan.groups):
            plan.groups.append((pid, part.label, parent))
        parent = pid
    if group.strip() and phase == "implement":
        gid = f"{parent}-{_slug(group)}"
        if all(g[0] != gid for g in plan.groups):
            plan.groups.append((gid, short(group.strip(), 40), parent))
        return gid
    return parent


def ensure_part_coverage(plan: WorkingPlan, part: Part, new_ids: list[str], rs: RequirementSet, kind: str,
                         ids: IdAllocator, *, multi_part: bool, allowed: frozenset[str]) -> None:
    """Every plannable requirement of the part ends up in a build or test step: a missed one joins the build step
    with the most words in common, or gets its own rule-made step; a part without tests gets one."""
    tasks = [t for t in plan.tasks if t.id in new_ids]
    covered = {r for t in tasks for r in t.requirement_ids}
    missing = [r for r in part.requirements if r.id not in covered and r.id not in plan.flagged]
    builds = [t for t in tasks if t.phase == "implement"]
    for r in missing:
        best = max(builds, key=lambda t: _overlap(r.text, t.title + " " + t.description), default=None)
        if best is not None and _overlap(r.text, best.title + " " + best.description) >= 0.25:
            updated = best.model_copy(update={
                "requirement_ids": [*best.requirement_ids, r.id],
                "acceptance_criteria": [*best.acceptance_criteria, f"{r.id}: {r.text}"][:8]})
            plan.replace(updated)
            builds = [updated if t.id == best.id else t for t in builds]
            plan.repairs.append(f"{r.id} was not in any step: added to {best.id} ({best.title})")
        else:
            draft = rule_draft(part, [r], kind)
            made = add_part(plan, part, draft, rs, kind, ids, multi_part=multi_part, allowed=allowed,
                            source="rules")
            new_ids.extend(made)
            plan.repairs.append(f"{r.id} was not in any step: added rule-made steps {', '.join(made)}")
    tasks = [t for t in plan.tasks if t.id in new_ids]
    if not any(t.phase == "test" for t in tasks) and any(t.phase == "implement" for t in tasks):
        reqs = sorted({r for t in tasks for r in t.requirement_ids})
        draft = DraftPlan(steps=[DraftStep(key="t", title=f"Test {part.label}", phase="test", requirement_ids=reqs,
                                           depends_on=[], acceptance_criteria=[f"{r} works as stated"
                                                                               for r in reqs][:6])])
        made = add_part(plan, part, draft, rs, kind, ids, multi_part=multi_part, allowed=allowed, source="rules")
        new_ids.extend(made)
        plan.repairs.append(f"{part.label} had no test step: added {made[0]}")


def add_deliverables(plan: WorkingPlan, rs: RequirementSet, kind: str, ids: IdAllocator,
                     allowed: frozenset[str]) -> dict[str, list[str]]:
    """A document step per document-like deliverable (README, report, slides); code deliverables are produced by
    the build steps; anything else is checked in the final review. Returns deliverable id -> task ids."""
    out: dict[str, list[str]] = {}
    builds = [t.id for t in plan.tasks if t.phase == "implement"]
    capability = PHASE_CAPABILITY[kind]["document"]
    if capability not in allowed:
        capability = PHASE_CAPABILITY["software"]["document"]
    for d in rs.deliverables:
        text = f"{d.name} {d.format}"
        if DOC_DELIVERABLE.search(text) and not re.search(r"\b(zip|source|code)\b", d.name, re.I):
            tid = ids.new(plan.ids())
            plan.tasks.append(PlanTask(
                id=tid, title=short(f"Prepare {d.name}", 120), agent_capability=capability, phase="document",
                description=f"Produce the deliverable {d.id}: {d.name}" + (f" ({d.format})" if d.format else "") + ".",
                acceptance_criteria=[f"{d.id} exists: {d.name}" + (f" as {d.format}" if d.format else ""),
                                     "it matches the finished, tested work"],
                priority=Priority.NORMAL, est_effort=EFFORT["document"]))
            plan.task_group[tid] = phase_group_id("document")
            out[d.id] = [tid]
        elif builds and re.search(r"\b(source|code|zip|program|repository|repo|script)\b", text, re.I):
            out[d.id] = list(builds)
        else:
            out[d.id] = ["review"]
    if not any(t.phase == "document" for t in plan.tasks):
        tid = ids.new(plan.ids())
        what = "README" if kind == "software" else "final document"
        plan.tasks.append(PlanTask(
            id=tid, title=f"Write the {what}", agent_capability=capability, phase="document",
            description="Explain what was built, how to run it and how it was tested." if kind == "software"
            else "Assemble the checked sections into the final document.",
            acceptance_criteria=["someone new can follow it", "it matches the finished, tested work"],
            priority=Priority.NORMAL, est_effort=EFFORT["document"]))
        plan.task_group[tid] = phase_group_id("document")
    return out


_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset([
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "be", "must", "should", "may",
    "can", "shall", "it", "its", "each", "every", "when", "that", "this", "by", "as", "at", "from", "your", "you"])


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa) if wa else 0.0


overlap = _overlap

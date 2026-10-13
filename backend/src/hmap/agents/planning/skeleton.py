"""Plan skeleton (spec item 3.1): the project kind, its parts (one per upload folder), the template spine, and what
people must look at before approving (open questions, low-confidence requirements, things only a person can do).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.planning.model import PHASES, WorkingPlan
from hmap.agents.planning.templates import HUMAN_ONLY, SPINE, detect_kind
from hmap.core.contracts import Priority
from hmap.core.contracts.domain import PlanTask, Requirement, RequirementSet

LOW_CONFIDENCE = 0.7
PHASE_NAMES = {"research": "Research", "design": "Design", "implement": "Build", "test": "Test",
               "document": "Document", "review": "Review"}


@dataclass
class Part:
    """One part of the work: an upload folder ("Part A"), or the whole request when there are no folders."""

    id: str                      # "p1", "p2", ... (stable: folders in name order)
    name: str                    # folder name, or "" for a single-part project
    requirements: list[Requirement] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)  # requirement id -> section heading

    @property
    def label(self) -> str:
        return self.name or "the work"


def phase_group_id(phase: str) -> str:
    return f"g-{phase}"


def section_map(document_model: dict[str, Any] | None) -> dict[tuple[str, str], str]:
    """(doc_id, block_id) -> the innermost section heading, from Member 2's ``document-model`` (read as plain JSON
    so this plug-in does not depend on Member 2's code)."""
    out: dict[tuple[str, str], str] = {}
    for doc in (document_model or {}).get("documents") or []:
        for block in doc.get("blocks") or []:
            path = block.get("section_path") or []
            if path and block.get("id"):
                out[(str(doc.get("doc_id")), str(block["id"]))] = str(path[-1])
    return out


def build_parts(rs: RequirementSet, sections: dict[tuple[str, str], str] | None = None) -> list[Part]:
    folders = sorted({r.source_ref.folder for r in rs.requirements if r.source_ref.folder})
    if len(folders) <= 1:
        parts = [Part("p1", folders[0] if folders else "")]
        index = {f: parts[0] for f in [*folders, None]}
    else:
        parts = [Part(f"p{i}", f) for i, f in enumerate(folders, start=1)]
        index = {p.name: p for p in parts}
        if any(not r.source_ref.folder for r in rs.requirements):
            parts.append(Part(f"p{len(parts) + 1}", "General"))
            index[None] = parts[-1]
    for r in rs.requirements:
        part = index[r.source_ref.folder if r.source_ref.folder in index else None]
        part.requirements.append(r)
        for block in r.source_ref.block_ids[:1]:
            heading = (sections or {}).get((r.source_ref.doc_id, block))
            if heading:
                part.sections[r.id] = heading
    return [p for p in parts if p.requirements] or parts[:1]


def human_only(rs: RequirementSet) -> dict[str, str]:
    """Requirements no agent can carry out (a demo in person, uploading to the course portal): flagged with a
    reason instead of being turned into tasks."""
    out: dict[str, str] = {}
    for r in rs.requirements:
        if HUMAN_ONLY.search(r.text):
            out[r.id] = "needs a person (e.g. a live demo or handing in on the course portal); not given to an agent"
    return out


def review_questions(rs: RequirementSet) -> tuple[list[str], list[str]]:
    """Questions to show before approval: Member 2's open questions plus every low-confidence requirement."""
    questions = list(rs.open_questions)
    low = [r.id for r in rs.requirements if r.confidence < LOW_CONFIDENCE]
    for r in rs.requirements:
        if r.confidence < LOW_CONFIDENCE:
            questions.append(f"Is {r.id} right? It was read with low confidence: \"{r.text}\"")
    return questions, low


def rule_research_questions(rs: RequirementSet, parts: list[Part], kind: str) -> list[str]:
    """Research seeds without a model: one per technology constraint and one per part (Member 5 refines them)."""
    out: list[str] = []
    for c in rs.constraints:
        if c.kind == "technology":
            out.append(f"How should the work follow this constraint, and what are the pitfalls: \"{c.text}\"?")
    for p in parts:
        must = [r for r in p.requirements if r.priority == "must"][:3] or p.requirements[:3]
        if not must:
            continue
        focus = "; ".join(_short(r.text, 80) for r in must)
        what = "designs" if kind == "software" else "sources and arguments"
        out.append(f"What {what} fit {p.label}: {focus}?")
    return out[:6] or ["What do we need to learn before starting this work?"]


def build_skeleton(rs: RequirementSet, kind: str | None = None) -> tuple[WorkingPlan, str]:
    """The spine (research, verify, design, review) with its groups; parts are added by the decomposer."""
    kind = kind or detect_kind([r.text for r in rs.requirements] + [c.text for c in rs.constraints] +
                               [f"{d.name} {d.format}" for d in rs.deliverables])
    plan = WorkingPlan(tasks=[])
    for phase in PHASES:
        plan.groups.append((phase_group_id(phase), PHASE_NAMES[phase], None))
    for step in SPINE[kind]:
        criteria = list(step.acceptance)
        if step.id == "review":
            criteria += [f"{c.id} respected: {c.text}" for c in rs.constraints]
            criteria += [f"{d.id} handed in: {d.name}" + (f" ({d.format})" if d.format else "")
                         for d in rs.deliverables]
            if rs.evaluation_criteria:
                total = rs.total_marks if rs.total_marks is not None else sum(e.max_marks
                                                                                for e in rs.evaluation_criteria)
                criteria.append(f"checked against the marking scheme ({len(rs.evaluation_criteria)} criteria, "
                                f"{total:g} marks)")
        if step.id == "design":
            criteria += [f"{c.id} respected: {c.text}" for c in rs.constraints if c.kind == "technology"]
        task = PlanTask(id=step.id, title=step.title, description=step.description, agent_capability=step.capability,
                        acceptance_criteria=criteria, phase=step.phase,
                        priority=Priority.NORMAL, est_effort=step.effort)
        plan.tasks.append(task)
        plan.task_group[task.id] = phase_group_id(step.phase)
    plan.add_edge("research", "verify", "template")
    plan.add_edge("verify", "design", "template")
    return plan, kind


def _short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


short = _short

"""Planning data that is not part of the shared ``TaskGraph`` contract: the ``plan-report`` artifact (how the plan
was made, what was repaired, what is flagged, the schedule) and the in-progress plan the pipeline stages pass along.

The ``TaskGraph`` stays the only thing the Manager and other members read; the report is for people (the UI) and for
evaluation. Its fields are additive-only like a contract.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from hmap.core.contracts.domain import PlanTask

PROMPT_VERSION = "2"

# Phases in spine order (``PlanTask.phase`` values). ``verify`` tasks use the research phase.
PHASES: tuple[str, ...] = ("research", "design", "implement", "test", "document", "review")
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}

EdgeSource = Literal["template", "rule", "dataflow", "llm", "human", "repair"]
Severity = Literal["error", "warning"]


class Issue(BaseModel):
    code: str
    severity: Severity = "error"
    message: str
    task_id: str | None = None
    requirement_id: str | None = None


class Schedule(BaseModel):
    layers: list[list[str]] = Field(default_factory=list, description="parallel layers (topological generations)")
    critical_path: list[str] = Field(default_factory=list)
    earliest_start: dict[str, float] = Field(default_factory=dict, description="hours from the start")
    slack: dict[str, float] = Field(default_factory=dict, description="hours a task may slip without delay")
    total_effort: float = 0.0
    makespan: float = Field(default=0.0, description="length of the critical path in hours (unlimited workers)")


class PlanReport(BaseModel):
    """Artifact ``plan-report`` (one version per ``task-graph`` version)."""

    graph_version: int = 1
    origin: Literal["generated", "edited", "replanned"] = "generated"
    method: Literal["llm", "rules", "mixed"] = "rules"
    project_kind: str = "software"
    prompt_version: str = PROMPT_VERSION
    answered_by: dict[str, int] = Field(default_factory=dict, description="provider:model -> calls it answered")
    llm_calls: int = 0
    fallbacks: list[str] = Field(default_factory=list, description="parts planned by rules because the model failed")
    requirement_set: dict[str, str | int] | None = Field(default=None,
                                                          description="{artifact_id, version} the plan was made from")
    repairs: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list, description="problems left after repair (warnings)")
    flagged: dict[str, str] = Field(default_factory=dict, description="requirement id -> why no task covers it")
    deliverables: dict[str, list[str]] = Field(default_factory=dict, description="deliverable id -> task ids")
    questions: list[str] = Field(default_factory=list, description="to answer before approving")
    low_confidence: list[str] = Field(default_factory=list, description="requirement ids with confidence < 0.7")
    edges: dict[str, int] = Field(default_factory=dict, description="dependency source -> count (after reduction)")
    schedule: Schedule = Field(default_factory=Schedule)
    feedback: str | None = Field(default=None, description="the human feedback a replan answered")
    author: str | None = None


@dataclass
class WorkingPlan:
    """A plan being built: tasks plus where each dependency came from (cycle repair drops model edges first)."""

    tasks: list[PlanTask]
    edge_source: dict[tuple[str, str], EdgeSource] = field(default_factory=dict)
    groups: list[tuple[str, str, str | None]] = field(default_factory=list)  # (id, name, parent id)
    task_group: dict[str, str] = field(default_factory=dict)  # task id -> group id
    flagged: dict[str, str] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    def task(self, task_id: str) -> PlanTask | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def ids(self) -> set[str]:
        return {t.id for t in self.tasks}

    def add_edge(self, before: str, after: str, source: EdgeSource) -> bool:
        """``after`` depends on ``before``. Returns False if it already did (the first source is kept)."""
        if before == after:
            return False
        for i, t in enumerate(self.tasks):
            if t.id == after:
                if before in t.depends_on:
                    return False
                self.tasks[i] = t.model_copy(update={"depends_on": [*t.depends_on, before]})
                self.edge_source.setdefault((before, after), source)
                return True
        return False

    def remove_edge(self, before: str, after: str) -> None:
        for i, t in enumerate(self.tasks):
            if t.id == after and before in t.depends_on:
                self.tasks[i] = t.model_copy(update={"depends_on": [d for d in t.depends_on if d != before]})
        self.edge_source.pop((before, after), None)

    def replace(self, task: PlanTask) -> None:
        self.tasks = [task if t.id == task.id else t for t in self.tasks]

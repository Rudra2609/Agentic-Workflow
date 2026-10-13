"""Cross-sprint "handoff" contracts (doc 01 §4). Producers store these as JSON artifacts; consumers validate them.

Fixed in Sprint 1 so Members 2-11 can build test data now. Changes are additive only (new optional fields ->
minor bump). Each class names its producer -> consumer.
"""

from typing import Any, Literal

from pydantic import AwareDatetime, Field, computed_field, model_validator

from hmap.core.contracts.common import (
    ArtifactRef,
    Confidence,
    ContextRef,
    Contract,
    NonEmptyStr,
    Priority,
    Sha256Hex,
)

# ============================================================== M2 -> M3 (+M10): RequirementSet


class SourceRef(Contract):
    """Where an item came from in the source document (traceability, Sprint 2)."""

    doc_id: NonEmptyStr
    page: int | None = Field(default=None, ge=1)
    block_ids: list[str] = Field(default_factory=list)
    char_span: tuple[int, int] | None = None
    quote: str | None = Field(default=None, description="verbatim text; verified by string match")
    folder: str | None = Field(default=None, description="upload folder of the source document (e.g. 'Part A'); "
                               "the planner may treat one folder as one part of the work")


class Requirement(Contract):
    id: str = Field(pattern=r"^R\d+$")
    text: NonEmptyStr
    type: Literal["functional", "non_functional"] = "functional"
    priority: Literal["must", "should", "could"] = "must"
    source_ref: SourceRef
    confidence: Confidence = 1.0


class Constraint(Contract):
    id: str = Field(pattern=r"^C\d+$")
    text: NonEmptyStr
    kind: Literal["technology", "format", "process", "resource", "other"] = "other"
    source_ref: SourceRef | None = None


class Deliverable(Contract):
    id: str = Field(pattern=r"^D\d+$")
    name: NonEmptyStr
    format: str = ""
    source_ref: SourceRef | None = None


class RubricLevel(Contract):
    label: NonEmptyStr
    description: str = ""
    marks: float | None = Field(default=None, ge=0)


class EvaluationCriterion(Contract):
    id: str = Field(pattern=r"^E\d+$")
    criterion: NonEmptyStr
    max_marks: float = Field(ge=0)
    rubric_levels: list[RubricLevel] = Field(default_factory=list)
    source_ref: SourceRef | None = None


class RequirementSet(Contract):
    project_id: NonEmptyStr
    source_docs: list[ArtifactRef] = Field(default_factory=list)
    requirements: list[Requirement]
    constraints: list[Constraint] = Field(default_factory=list)
    deliverables: list[Deliverable] = Field(default_factory=list)
    evaluation_criteria: list[EvaluationCriterion] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    total_marks: float | None = Field(default=None, ge=0, description="total stated in the document, if any")

    @model_validator(mode="after")
    def _check(self) -> "RequirementSet":
        ids = [r.id for r in self.requirements] + [c.id for c in self.constraints] + \
            [d.id for d in self.deliverables] + [e.id for e in self.evaluation_criteria]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate ids: {sorted(dupes)}")
        if self.total_marks is not None and self.evaluation_criteria:
            got = sum(c.max_marks for c in self.evaluation_criteria)
            if abs(got - self.total_marks) > 1e-6:
                raise ValueError(f"criteria marks sum to {got}, document total is {self.total_marks}")
        return self


# ============================================================== M3 -> Manager (+all agents): TaskGraph


class PlanTask(Contract):
    id: NonEmptyStr
    title: NonEmptyStr
    description: str = ""
    agent_capability: NonEmptyStr
    requirement_ids: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    priority: Priority = Priority.NORMAL
    est_effort: float | None = Field(default=None, ge=0, description="hours")
    phase: Literal["research", "design", "implement", "test", "document", "review"] = "implement"
    research_questions: list[str] = Field(default_factory=list, description="seed for a ResearchBrief (M5)")


class Phase(Contract):
    id: NonEmptyStr
    name: NonEmptyStr
    task_ids: list[str] = Field(default_factory=list)
    parent_id: str | None = Field(default=None, description="the enclosing phase / group (plan hierarchy, Sprint 3); "
                                  "tasks stay executable leaves, groups are never run")


class Milestone(Contract):
    name: NonEmptyStr
    task_ids: list[str] = Field(default_factory=list)


class Roadmap(Contract):
    phases: list[Phase] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    markdown: str | None = None


class TaskGraph(Contract):
    project_id: NonEmptyStr
    version: int = Field(default=1, ge=1)
    tasks: list[PlanTask] = Field(min_length=1)
    roadmap: Roadmap = Field(default_factory=Roadmap)
    coverage_matrix: dict[str, list[str]] = Field(default_factory=dict, description="requirement id -> task ids")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def edges(self) -> list[dict[str, str]]:
        """``[{from, to}]`` derived from ``depends_on`` (single source of truth)."""
        return [{"from": d, "to": t.id} for t in self.tasks for d in t.depends_on]

    @model_validator(mode="after")
    def _check(self) -> "TaskGraph":
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate task ids")
        known = set(ids)
        for t in self.tasks:
            missing = [d for d in t.depends_on if d not in known]
            if missing:
                raise ValueError(f"task {t.id} depends on unknown {missing}")
        for req, tids in self.coverage_matrix.items():
            if any(tid not in known for tid in tids):
                raise ValueError(f"coverage for {req} references unknown task")
        # cycle check (iterative DFS, colours)
        deps = {t.id: t.depends_on for t in self.tasks}
        state: dict[str, int] = {}
        for root in ids:
            if state.get(root):
                continue
            stack: list[tuple[str, int]] = [(root, 0)]
            while stack:
                node, i = stack.pop()
                if i == 0:
                    state[node] = 1
                children = deps[node]
                if i < len(children):
                    stack.append((node, i + 1))
                    child = children[i]
                    if state.get(child) == 1:
                        raise ValueError(f"dependency cycle through {child}")
                    if not state.get(child):
                        stack.append((child, 0))
                else:
                    state[node] = 2
        return self

    def task(self, task_id: str) -> PlanTask:
        return next(t for t in self.tasks if t.id == task_id)


# ============================================================== M4 <-> any agent: refinement


IssueCategory = Literal["FORMAT", "SCHEMA", "OMISSION", "HALLUCINATION", "FACTUAL", "LOGIC",
                        "REQUIREMENT_VIOLATION", "CONSISTENCY", "STYLE", "SAFETY"]
Severity = Literal["info", "minor", "major", "critical"]


class Issue(Contract):
    category: IssueCategory
    severity: Severity
    description: NonEmptyStr
    location: str | None = None
    evidence: str | None = None
    fix_hint: str | None = None


class Critique(Contract):
    score: Confidence
    issues: list[Issue] = Field(default_factory=list)
    critic: str | None = None


class RefinementSpec(Contract):
    producer: NonEmptyStr
    critics: list[str] = Field(min_length=1)
    reviser: NonEmptyStr
    stop_policy: dict[str, Any] = Field(default_factory=dict, description="e.g. {'max_iters': 3, 'threshold': 0.9}")


class RefinementIteration(Contract):
    index: int = Field(ge=0)
    output_ref: ArtifactRef | None = None
    critique: Critique
    score: Confidence
    tokens: int = Field(default=0, ge=0)
    duration_s: float = Field(default=0.0, ge=0)


class RefinementTrace(Contract):
    spec: RefinementSpec
    iterations: list[RefinementIteration] = Field(default_factory=list)
    best_iteration: int | None = Field(default=None, ge=0)
    stop_reason: Literal["max_iters", "threshold", "no_critical_issues", "plateau", "budget", "tests_pass",
                         "cancelled", "error"]


# ============================================================== Manager -> M5 -> M6: research


class ResearchBudget(Contract):
    max_rounds: int = Field(default=3, ge=1)
    max_sources: int = Field(default=20, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_seconds: int | None = Field(default=None, ge=1)


class ResearchBrief(Contract):
    task_id: NonEmptyStr
    questions: list[NonEmptyStr] = Field(min_length=1)
    scope: str = ""
    constraints: list[str] = Field(default_factory=list)
    budget: ResearchBudget = Field(default_factory=ResearchBudget)


class Evidence(Contract):
    id: NonEmptyStr
    url: NonEmptyStr
    quote: NonEmptyStr = Field(description="verbatim from the fetched content")
    content_sha256: Sha256Hex
    retrieved_at: AwareDatetime
    sub_question: str | None = None
    page_artifact: ArtifactRef | None = Field(default=None, description="cached page so M6 can re-check")


class Claim(Contract):
    id: NonEmptyStr
    text: NonEmptyStr
    evidence_ids: list[str] = Field(min_length=1)


class Source(Contract):
    url: NonEmptyStr
    title: str = ""
    score: float | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class ResearchReport(Contract):
    task_id: NonEmptyStr
    questions: list[str] = Field(default_factory=list)
    claims: list[Claim]
    evidence: list[Evidence]
    sources: list[Source] = Field(default_factory=list)
    coverage: dict[str, float] = Field(default_factory=dict, description="sub-question -> 0..1")
    stop_reason: NonEmptyStr
    summary_markdown: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "ResearchReport":
        known = {e.id for e in self.evidence}
        for c in self.claims:
            missing = [e for e in c.evidence_ids if e not in known]
            if missing:
                raise ValueError(f"claim {c.id} cites unknown evidence {missing}")
        return self


# ============================================================== M6 -> Manager/M10: verification

Verdict = Literal["VERIFIED", "UNSUPPORTED", "CONFLICTING", "NEEDS_MORE_RESEARCH"]


class ClaimVerdict(Contract):
    claim_id: NonEmptyStr
    verdict: Verdict
    confidence: Confidence
    supporting: list[str] = Field(default_factory=list, description="evidence ids or URLs")
    contradicting: list[str] = Field(default_factory=list)
    explanation: str = ""


class VerificationReport(Contract):
    task_id: NonEmptyStr
    research_report_ref: ArtifactRef | None = None
    claim_verdicts: list[ClaimVerdict]
    follow_up_questions: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> dict[str, int]:
        out = {"verified": 0, "unsupported": 0, "conflicting": 0, "needs_more": 0}
        key = {"VERIFIED": "verified", "UNSUPPORTED": "unsupported", "CONFLICTING": "conflicting",
               "NEEDS_MORE_RESEARCH": "needs_more"}
        for v in self.claim_verdicts:
            out[key[v.verdict]] += 1
        return out


# ============================================================== M7 -> M8/M9/M10: code


class CommandRun(Contract):
    cmd: NonEmptyStr
    exit_code: int
    duration_s: float = Field(default=0.0, ge=0)


class CodeChangeSet(Contract):
    task_id: NonEmptyStr
    workspace_ref: ArtifactRef
    patch_ref: ArtifactRef | None = None
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[CommandRun] = Field(default_factory=list)
    notes: str = ""


# ============================================================== M8 -> M7/M10: tests

StageName = Literal["static", "build", "unit", "integration", "security", "execution"]


class StageResult(Contract):
    status: Literal["passed", "failed", "skipped", "error"]
    output_ref: ArtifactRef | None = None
    duration_s: float = Field(default=0.0, ge=0)


class TestFailure(Contract):
    __test__ = False  # not a pytest test class

    category: Literal["SYNTAX", "IMPORT", "ASSERTION", "TIMEOUT", "CRASH", "SECURITY", "LINT", "ENV"]
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    message: NonEmptyStr
    hint: str | None = None


class TestReport(Contract):
    __test__ = False

    task_id: NonEmptyStr
    changeset_ref: ArtifactRef | None = None
    stages: dict[StageName, StageResult]
    failures: list[TestFailure] = Field(default_factory=list)
    passed: bool
    coverage: float | None = Field(default=None, ge=0, le=100)
    exec_log_ref: ArtifactRef | None = None


# ============================================================== M9 -> M10: documentation


class AccuracyReport(Contract):
    grounded_pct: float = Field(ge=0, le=100)
    ungrounded_claims: list[str] = Field(default_factory=list)
    examples_verified: int = Field(default=0, ge=0)
    examples_failed: int = Field(default=0, ge=0)


class DocBundle(Contract):
    task_id: NonEmptyStr
    readme_ref: ArtifactRef | None = None
    api_docs_ref: ArtifactRef | None = None
    architecture_ref: ArtifactRef | None = None
    summaries_ref: ArtifactRef | None = None
    report_sections_ref: ArtifactRef | None = None
    accuracy_report: AccuracyReport


# ============================================================== M10 -> Manager: review


class RequirementResult(Contract):
    req_id: NonEmptyStr
    verdict: Literal["PASS", "PARTIAL", "FAIL"]
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class RubricScore(Contract):
    criterion_id: NonEmptyStr
    score: float = Field(ge=0)
    max_marks: float = Field(ge=0)


class ReviewFailure(Contract):
    category: Literal["MISSING", "INCORRECT", "UNTESTED", "UNSUPPORTED_CLAIM", "DOC_MISMATCH", "QUALITY"]
    requirement_id: str | None = None
    responsible_task_id: str | None = None
    description: NonEmptyStr


class RevisionPlan(Contract):
    task_id: NonEmptyStr
    action: Literal["revise", "rerun", "replan", "escalate"]
    required_changes: list[str] = Field(default_factory=list)
    context_refs: list[ContextRef] = Field(default_factory=list)


class ReviewReport(Contract):
    project_id: NonEmptyStr
    requirement_results: list[RequirementResult]
    rubric_scores: list[RubricScore] = Field(default_factory=list)
    failures: list[ReviewFailure] = Field(default_factory=list)
    revision_requests: list[RevisionPlan] = Field(default_factory=list)
    overall: Confidence
    recommendation: Literal["PASS", "REVISE", "ESCALATE"]


# ============================================================== M11 -> all: models


class ModelSpec(Contract):
    id: NonEmptyStr
    family: str = ""
    params_b: float | None = Field(default=None, ge=0)
    quant: str | None = None
    ctx: int | None = Field(default=None, ge=1)
    backend: Literal["ollama", "llamacpp", "mlx", "cloud"] = "ollama"
    mem_gb: float | None = Field(default=None, ge=0)
    tok_s: float | None = Field(default=None, ge=0)
    roles_ok: list[str] = Field(default_factory=list)
    status: Literal["installed", "available", "missing", "disabled"] = "installed"


class RouteDecision(Contract):
    role: NonEmptyStr
    model: NonEmptyStr
    backend: NonEmptyStr
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class BenchmarkResult(Contract):
    model: NonEmptyStr
    quant: str | None = None
    role: NonEmptyStr
    task: NonEmptyStr
    quality_score: Confidence
    tok_s: float | None = Field(default=None, ge=0)
    ttft_s: float | None = Field(default=None, ge=0)
    mem_gb: float | None = Field(default=None, ge=0)


# Registry used by schema export and contract tests.
DOMAIN_MODELS: dict[str, type[Contract]] = {
    "RequirementSet": RequirementSet,
    "TaskGraph": TaskGraph,
    "RefinementSpec": RefinementSpec,
    "RefinementTrace": RefinementTrace,
    "ResearchBrief": ResearchBrief,
    "ResearchReport": ResearchReport,
    "VerificationReport": VerificationReport,
    "CodeChangeSet": CodeChangeSet,
    "TestReport": TestReport,
    "DocBundle": DocBundle,
    "ReviewReport": ReviewReport,
    "ModelSpec": ModelSpec,
    "RouteDecision": RouteDecision,
    "BenchmarkResult": BenchmarkResult,
}

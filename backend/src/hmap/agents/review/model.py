"""Artifact types, ids and the review's working models (Sprint 10, plan D1, D8).

Per review task: ``review-report`` ``rr-<task_id>`` (the contract output, first in the result), ``review-evidence``
``rev-<task_id>`` (one :class:`Item` per requirement / constraint / deliverable / rubric criterion / change request,
with the quoted evidence and how it was decided) and ``review-trace`` ``rtr-<task_id>`` (round, judge calls, the
recovery plan, the stop reason). A person's decision on a report is a ``review-decision`` ``rdc-<task_id>``
(versioned: overrides, accept with notes, request changes).

The evidence shape is the prototype's (``samples/review/calibration/items.jsonl``), so the calibration set and the
seeded scenarios run through the same checks as a real project.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

REPORT_TYPE = "review-report"
EVIDENCE_TYPE = "review-evidence"
TRACE_TYPE = "review-trace"
DECISION_TYPE = "review-decision"

Verdict = Literal["PASS", "PARTIAL", "FAIL"]
CheckVerdict = Literal["PASS", "PARTIAL", "FAIL", "UNDECIDED"]
Category = Literal["MISSING", "INCORRECT", "UNTESTED", "UNSUPPORTED_CLAIM", "DOC_MISMATCH", "QUALITY"]
Kind = Literal["requirement", "constraint", "deliverable", "criterion", "change"]
VERDICTS: tuple[str, ...] = ("PASS", "PARTIAL", "FAIL")


def report_id(task_id: str) -> str:
    return f"rr-{task_id}"


def evidence_id(task_id: str) -> str:
    return f"rev-{task_id}"


def trace_id(task_id: str) -> str:
    return f"rtr-{task_id}"


def decision_id(task_id: str) -> str:
    return f"rdc-{task_id}"


class TestEv(BaseModel):
    """One test run that covers the item (the newest round of a test -> revise loop)."""

    __test__ = False  # not a pytest test class

    name: str
    status: str                       # passed / failed / error / timeout / skipped
    covers: list[str] = Field(default_factory=list)
    module: str | None = None         # the file a failure points at
    task_id: str | None = None        # the test.run task
    coding_task_id: str | None = None
    detail: str = ""
    flaky: bool = False
    round: int = 0
    pending: bool = False             # Member 8's loop will run another round (plan D9)


class DeliverableEv(BaseModel):
    name: str
    present: bool | None = None       # None: the rules could not tell
    where: str = ""


class VerificationEv(BaseModel):
    claim: str
    verdict: str                      # supported / unsupported / contradicted
    task_id: str | None = None


class Evidence(BaseModel):
    deliverables: list[DeliverableEv] = Field(default_factory=list)
    tests: list[TestEv] = Field(default_factory=list)
    verification: list[VerificationEv] = Field(default_factory=list)
    doc_ungrounded: list[str] = Field(default_factory=list)
    producer_note: str = ""                                    # the producer's own words: a claim, not evidence
    doc_status: str | None = None                              # docgen coverage: shown / not shown / conflict
    violations: list[str] = Field(default_factory=list)        # a constraint the code breaks
    facts: list[str] = Field(default_factory=list)             # short quoted facts ("server.py imports threading")
    stub: bool = False                                         # every covering result came from a stub agent


class Item(BaseModel):
    id: str                                   # R1 / C1 / D1 / E1 / H1 (or a synthetic "DOCS")
    kind: Kind = "requirement"
    text: str
    acceptance: str = ""
    priority: str = "must"
    covering: list[str] = Field(default_factory=list)          # task ids (Manager ids when known, else plan ids)
    evidence: Evidence = Field(default_factory=Evidence)
    max_marks: float | None = None                             # criteria only
    rubric_levels: list[dict[str, Any]] = Field(default_factory=list)
    mode: Literal["software", "document"] = "software"


class Check(BaseModel):
    verdict: CheckVerdict
    reasons: list[str] = Field(default_factory=list)
    category: Category | None = None
    module: str | None = None                                  # the file a failing test points at
    no_action: bool = False                                    # nothing a revision can fix (stub output)


class JudgeVote(BaseModel):
    order: Literal["given", "reversed"]
    verdict: Verdict
    rationale: str = ""
    cited: list[str] = Field(default_factory=list)
    valid_citations: bool = True


class Decided(BaseModel):
    """One item after checks, the judge and aggregation."""

    item: Item
    check: Check
    verdict: Verdict
    source: Literal["objective", "judge", "both", "none", "human"] = "objective"
    rationale: str = ""
    votes: list[JudgeVote] = Field(default_factory=list)
    order_sensitive: bool = False
    level: str | None = None                                   # criteria: the rubric level the judge picked
    score: float | None = None


class FailureRec(BaseModel):
    item_id: str
    category: Category
    task_id: str | None                    # None: no task covers it (a planning gap -> replan)
    capability: str | None = None
    why: str
    confidence: float = 1.0
    no_action: bool = False


class TaskInfo(BaseModel):
    """A row of the project's task table (from the recovery slot's ``assign_inputs``; plan T4)."""

    task_id: str
    capability: str
    plan_task_id: str | None = None
    title: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    state: str = ""
    replaced: bool = False
    original_task_id: str | None = None
    loop_origin: str | None = None
    recovery_round: int | None = None
    feedback: str = ""
    phase: str = ""
    results: list[str] = Field(default_factory=list)          # artifact ids of the newest successful execution
    created_at: str = ""


class ReviewTrace(BaseModel):
    task_id: str
    project_id: str
    execution_id: str
    status: Literal["running", "done"] = "running"
    round: int = 0
    mode: Literal["software", "document"] = "software"
    items: int = 0
    decided_by: dict[str, int] = Field(default_factory=dict)   # objective / judge / both / none
    judge_calls: int = 0
    judge_model_note: str = ""
    order_sensitive: list[str] = Field(default_factory=list)
    failures: list[FailureRec] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)         # actions, rerun, stop reason
    signature: list[str] = Field(default_factory=list)         # sorted "item:category" of this round
    history: list[list[str]] = Field(default_factory=list)     # earlier rounds' signatures
    completeness: float = 0.0
    recommendation: str = ""
    stop_reason: str | None = None
    notes: list[str] = Field(default_factory=list)
    flagged_text: int = 0                                      # AI-directed lines removed from producer text
    seconds: float = 0.0

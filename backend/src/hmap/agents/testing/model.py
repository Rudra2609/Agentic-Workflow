"""Artifact types, ids and the testing trace (Sprint 8, plan D12).

Per task: ``test-report`` ``tr-<task_id>`` (the contract output, first in the result), ``test-log`` ``tl-<task_id>``
(every stage's output, normalised; ``TestReport.exec_log_ref``), ``testing-trace`` ``tt-<task_id>`` (what ran, for
the UI, the eval and the test -> revise loop) and ``generated-tests`` ``gt-<task_id>`` when tests were written from
the acceptance criteria (plan D9).
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from hmap.core.contracts import ArtifactRef

REPORT_TYPE = "test-report"
LOG_TYPE = "test-log"
TRACE_TYPE = "testing-trace"
GENERATED_TYPE = "generated-tests"

STAGES: tuple[str, ...] = ("static", "build", "unit", "integration", "security", "execution")
Category = Literal["SYNTAX", "IMPORT", "ASSERTION", "TIMEOUT", "CRASH", "SECURITY", "LINT", "ENV"]
Status = Literal["passed", "failed", "skipped", "error"]


def report_id(task_id: str) -> str:
    return f"tr-{task_id}"


def log_id(task_id: str) -> str:
    return f"tl-{task_id}"


def trace_id(task_id: str) -> str:
    return f"tt-{task_id}"


def generated_id(task_id: str) -> str:
    return f"gt-{task_id}"


class StepRecord(BaseModel):
    """One command inside a stage (what ran, how it ended)."""

    stage: str
    name: str
    cmd: str
    exit_code: int | None = None
    timed_out: bool = False
    duration_s: float = 0.0
    output: str = ""


class StageRecord(BaseModel):
    name: str
    status: Status
    duration_s: float = 0.0
    detail: str = ""
    tests: int = 0          # unit / integration: tests run
    tests_failed: int = 0


class FailureRecord(BaseModel):
    """A failure as the analyser found it; ``TestFailure`` in the report is the contract view of it."""

    stage: str
    category: Category
    file: str | None = None
    line: int | None = None
    test: str | None = None
    message: str
    hint: str | None = None
    hint_by: Literal["rule", "model", "none"] = "rule"
    category_by: Literal["rule", "model"] = "rule"
    generated: bool = False      # from a generated test (plan D9): never triggers a revision on its own
    flaky: bool = False
    needs_model: bool = False    # the rules found no exception type; ``classify`` decides (plan D6)
    fuzz: bool = False           # found by fuzzing (stretch): reported, never counted, never sent for a fix alone

    def short(self) -> str:
        where = f"{self.file}:{self.line}" if self.file and self.line else (self.file or self.test or self.stage)
        return f"{self.category} {where}: {self.message[:160]}"


class LoopState(BaseModel):
    """The test -> revise loop this run belongs to (plan D10)."""

    round: int = 0                                   # 0 = the first test of a coding step
    origin_task_id: str | None = None                # the coding task the loop started from
    history: list[float] = Field(default_factory=list)   # pass ratio of each earlier round
    last_failures: list[str] = Field(default_factory=list)   # the previous round's failure signatures


class TestingTrace(BaseModel):
    __test__ = False  # not a pytest test class

    task_id: str
    project_id: str
    execution_id: str
    status: Literal["running", "done"] = "running"
    backend: Literal["docker", "local", "none"] = "none"
    isolation: str = ""
    workspace_from: str = ""                          # which artifact was tested (plan D8)
    workspace_ref: ArtifactRef | None = None
    changeset_ref: ArtifactRef | None = None
    coding_task_id: str | None = None
    objective: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    files: int = 0
    stages: list[StageRecord] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    flaky: list[str] = Field(default_factory=list)
    quarantined: list[str] = Field(default_factory=list)      # the project's quarantined tests after this run
    generated: dict[str, Any] = Field(default_factory=dict)   # {"kept": [...], "dropped": {...}, "files": n}
    coverage: float | None = None
    mutation: dict[str, Any] | None = None                   # {total, killed, score, survived[...]} when asked
    fuzz: dict[str, Any] | None = None                       # {targets, examples, findings} when asked
    dependencies: dict[str, Any] | None = None               # {audited, unpinned, vulnerable, source}
    language: str = "python"
    passed: bool = False
    pass_ratio: float = 0.0
    loop: LoopState = Field(default_factory=LoopState)
    model_calls: int = 0
    tokens: int = 0
    seconds: float = 0.0
    notes: list[str] = Field(default_factory=list)

"""Artifact types, ids and the coding trace (Sprint 7, plan D3).

Per task: ``code-change-set`` ``ccs-<task_id>`` (the contract output, first in the result), ``workspace``
``ws-<task_id>`` (gzip tar of the full tree after the task), ``code-patch`` ``patch-<task_id>`` (this task's unified
diff) and ``coding-trace`` ``ct-<task_id>`` (what the agent did, for the UI, the eval and Member 11). Per project:
the workspace head ``wsh-<project_id>`` (plan D2), the tree every new code task starts from.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from hmap.core.contracts import ArtifactRef

CHANGESET_TYPE = "code-change-set"
WORKSPACE_TYPE = "workspace"
PATCH_TYPE = "code-patch"
TRACE_TYPE = "coding-trace"
HEAD_TYPE = "workspace-head"
WORKSPACE_MEDIA = "application/gzip"
PATCH_MEDIA = "text/x-diff"


def changeset_id(task_id: str) -> str:
    return f"ccs-{task_id}"


def workspace_id(task_id: str) -> str:
    return f"ws-{task_id}"


def patch_id(task_id: str) -> str:
    return f"patch-{task_id}"


def trace_id(task_id: str) -> str:
    return f"ct-{task_id}"


def head_id(project_id: str) -> str:
    return f"wsh-{project_id}"


StepKind = Literal["locate", "plan", "edit", "debug", "review", "revise"]


class Step(BaseModel):
    """One model call."""

    n: int
    kind: StepKind
    summary: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ok: bool = True


class EditRecord(BaseModel):
    step: int
    files: list[str] = Field(default_factory=list)
    ok: bool
    error: str | None = None
    notes: list[str] = Field(default_factory=list)


class CommandRecord(BaseModel):
    step: int
    cmd: str
    exit_code: int | None = None
    timed_out: bool = False
    duration_s: float = 0.0
    output: str = ""
    denied: str | None = None


class Check(BaseModel):
    """Result of the agent's own checks (plan D12): compile, lint, tests, import smoke."""

    name: Literal["compile", "lint", "tests", "imports"]
    status: Literal["passed", "failed", "skipped"]
    detail: str = ""


class CodingTrace(BaseModel):
    task_id: str
    project_id: str
    capability: str
    execution_id: str = ""
    status: Literal["running", "done"] = "running"
    objective: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    base: str = ""                      # where the workspace came from (plan D1)
    base_ref: ArtifactRef | None = None
    template: str | None = None
    revision_of: ArtifactRef | None = None
    revision_round: int = 0
    original_task_id: str | None = None
    required_changes: list[str] = Field(default_factory=list)
    located: list[dict[str, Any]] = Field(default_factory=list)   # [{path, score}]
    plan: dict[str, Any] | None = None
    steps: list[Step] = Field(default_factory=list)
    edits: list[EditRecord] = Field(default_factory=list)
    commands: list[CommandRecord] = Field(default_factory=list)
    denials: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)                # files that look like prompt injection (D22)
    checks: list[Check] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    outcome: Literal["success", "partial", "failure", ""] = ""
    notes: list[str] = Field(default_factory=list)
    head_version: int | None = None

    @property
    def model_calls(self) -> int:
        return len(self.steps)

    @property
    def tokens(self) -> int:
        return sum(s.prompt_tokens + s.completion_tokens for s in self.steps)

    def checks_passed(self) -> bool:
        return bool(self.checks) and all(c.status != "failed" for c in self.checks)

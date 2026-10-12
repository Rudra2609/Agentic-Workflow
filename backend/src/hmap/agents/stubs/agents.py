"""Sprint-1 stub agents (item 1.16): one per capability in ``STUBBED_CAPABILITIES`` plus ``echo``.

Each returns the canned contract example from ``DOMAIN_EXAMPLES`` with ``project_id``/``task_id`` rewritten to the
real task, stored as a JSON artifact, so the whole pipeline runs before the real agents exist. They report progress
and honour cancellation. ``inputs["stub_delay_s"]`` (<= 30 s) simulates work, for cancellation / chaos tests.
"""

import asyncio
from typing import Any, ClassVar

from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.contracts import capabilities as caps
from hmap.core.contracts.common import Contract
from hmap.core.contracts.examples import DOMAIN_EXAMPLES
from hmap.core.runtime.base import AgentContext, BaseAgent

MAX_DELAY_S = 30.0


async def simulate_work(task: TaskAssign, ctx: AgentContext) -> None:
    delay = min(float(task.inputs.get("stub_delay_s", 0) or 0), MAX_DELAY_S)
    loop = asyncio.get_running_loop()
    end = loop.time() + delay
    while (left := end - loop.time()) > 0:
        ctx.check_cancelled()
        await asyncio.sleep(min(0.05, left))
    ctx.check_cancelled()


def canned_output(example: str, task: TaskAssign, project_id: str) -> Contract:
    """The contract example re-validated with this task's ids (``project_id``/``task_id`` fields only)."""
    model = DOMAIN_EXAMPLES[example]
    data: dict[str, Any] = model.model_dump(mode="json")
    if "project_id" in data:
        data["project_id"] = project_id
    if "task_id" in data:
        data["task_id"] = task.task_id
    if example == "TestReport":  # a passing report, so the stub pipeline closes
        data.update(stages={"static": {"status": "passed"}, "unit": {"status": "passed"}}, failures=[], passed=True)
    if example == "ReviewReport":
        data.update(recommendation="PASS", failures=[], revision_requests=[])
    return type(model).model_validate(data)


class StubAgent(BaseAgent):
    """Base for the canned-output stubs; subclasses set ``capabilities``, ``example`` and ``artifact_type``."""

    is_stub = True
    max_slots = 4
    example: ClassVar[str] = ""
    artifact_type: ClassVar[str] = ""

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await ctx.progress(10, f"stub {task.capability}: started")
        await simulate_work(task, ctx)
        ref = await ctx.put_json(canned_output(self.example, task, ctx.project_id), artifact_type=self.artifact_type)
        await ctx.progress(100, f"stub {task.capability}: canned {self.example} stored")
        return ctx.result([ref], summary=f"stub {self.example} (canned contract example)", evidence=["stub"])


class EchoAgent(BaseAgent):
    name = "echo"
    capabilities = (caps.ECHO,)
    is_stub = True
    max_slots = 4

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await simulate_work(task, ctx)
        ref = await ctx.put_json({"echo": task.objective, "inputs": task.inputs}, artifact_type="echo")
        await ctx.progress(100, "echoed")
        return ctx.result([ref], summary="echoed")


class DocumentExtractStub(StubAgent):
    name = "stub-document-extract"
    capabilities = (caps.DOCUMENT_EXTRACT,)
    example, artifact_type = "RequirementSet", "requirement-set"


class PlanGenerateStub(StubAgent):
    name = "stub-plan-generate"
    capabilities = (caps.PLAN_GENERATE,)
    example, artifact_type = "TaskGraph", "task-graph"


class ResearchRunStub(StubAgent):
    name = "stub-research-run"
    capabilities = (caps.RESEARCH_RUN,)
    example, artifact_type = "ResearchReport", "research-report"


class VerifyClaimsStub(StubAgent):
    name = "stub-verify-claims"
    capabilities = (caps.VERIFY_CLAIMS,)
    example, artifact_type = "VerificationReport", "verification-report"


class CodeImplementStub(StubAgent):
    name = "stub-code-implement"
    capabilities = (caps.CODE_IMPLEMENT,)
    example, artifact_type = "CodeChangeSet", "code-change-set"


class TestRunStub(StubAgent):
    __test__ = False  # not a pytest test class
    name = "stub-test-run"
    capabilities = (caps.TEST_RUN,)
    example, artifact_type = "TestReport", "test-report"


class DocsGenerateStub(StubAgent):
    name = "stub-docs-generate"
    capabilities = (caps.DOCS_GENERATE,)
    example, artifact_type = "DocBundle", "doc-bundle"


class ReviewFinalStub(StubAgent):
    name = "stub-review-final"
    capabilities = (caps.REVIEW_FINAL,)
    example, artifact_type = "ReviewReport", "review-report"


CAPABILITY_STUBS: tuple[type[StubAgent], ...] = (
    DocumentExtractStub, PlanGenerateStub, ResearchRunStub, VerifyClaimsStub,
    CodeImplementStub, TestRunStub, DocsGenerateStub, ReviewFinalStub,
)

"""Capability names (routing keys for per-capability queues) and the descriptor agents register with."""

from typing import Annotated, Any

from pydantic import Field, StringConstraints

from hmap.core.contracts.common import Contract

ECHO = "echo"
DOCUMENT_EXTRACT = "document.extract"   # Member 2
PLAN_GENERATE = "plan.generate"         # Member 3
PLAN_REPLAN = "plan.replan"             # Member 3
REFINE_RUN = "refine.run"               # Member 4
RESEARCH_RUN = "research.run"           # Member 5
VERIFY_CLAIMS = "verify.claims"         # Member 6
CODE_IMPLEMENT = "code.implement"       # Member 7
CODE_REVISE = "code.revise"             # Member 7
TEST_RUN = "test.run"                   # Member 8
DOCS_GENERATE = "docs.generate"         # Member 9
DOCS_UPDATE = "docs.update"             # Member 9
REVIEW_FINAL = "review.final"           # Member 10

# Capabilities that Sprint 1 ships stubs for (doc 01 §5).
STUBBED_CAPABILITIES: tuple[str, ...] = (
    DOCUMENT_EXTRACT, PLAN_GENERATE, RESEARCH_RUN, VERIFY_CLAIMS,
    CODE_IMPLEMENT, TEST_RUN, DOCS_GENERATE, REVIEW_FINAL,
)

CapabilityName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")]


class CapabilityDescriptor(Contract):
    """Research §20: matched by name/version first, then load and health."""

    name: CapabilityName
    version: str = "1.0"
    inputs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict, description="e.g. {'max_concurrency': 2}")


# What each pipeline capability must return: (artifact_type, contract name in domain.DOMAIN_MODELS).
# The pipeline plug-in, the e2e tests and the plug-in conformance tests rely on this (doc 01 §4).
CAPABILITY_OUTPUTS: dict[str, tuple[str, str]] = {
    DOCUMENT_EXTRACT: ("requirement-set", "RequirementSet"),
    PLAN_GENERATE: ("task-graph", "TaskGraph"),
    RESEARCH_RUN: ("research-report", "ResearchReport"),
    VERIFY_CLAIMS: ("verification-report", "VerificationReport"),
    CODE_IMPLEMENT: ("code-change-set", "CodeChangeSet"),
    TEST_RUN: ("test-report", "TestReport"),
    DOCS_GENERATE: ("doc-bundle", "DocBundle"),
    REVIEW_FINAL: ("review-report", "ReviewReport"),
}

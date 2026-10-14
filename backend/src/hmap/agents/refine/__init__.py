"""Self-reflection and refinement library (Member 4, Sprint 4). Public interface (spec §7):

    from hmap.agents.refine import Refiner, ProgrammaticCritic, LLMRubricCritic, TargetedReviser, default_policy
    refiner = Refiner(producer=..., critics=[ProgrammaticCritic(check_citations), LLMRubricCritic(RESEARCH_RUBRIC)],
                      reviser=TargetedReviser(), stop=default_policy())
    result = await refiner.run(task_input, RefineContext(llm=ctx.llm))   # result.final_output / .trace / .stop_reason

Also: ``StopPolicy`` combinators without a ``Refiner`` (``stop``), ``ReflectionMemory`` (``reflexion``),
``@refinable`` / ``RefinementMixin`` / ``RefineSetup`` for new agents (``integration``), ``Plugin.refiners`` adapters
for existing ones (``adapters``), the error taxonomy (``taxonomy``) and traces (``trace``). Guide:
``docs/members/4/integration.md``.
"""

from hmap.agents.refine.core import (
    Attempt,
    Critic,
    Critique,
    Issue,
    RefineContext,
    RefinementResult,
    RefinementSpec,
    RefinementTrace,
    Reviser,
    Revision,
)
from hmap.agents.refine.critics import (
    GENERIC_RUBRIC,
    CompositeCritic,
    Criterion,
    LLMRubricCritic,
    ProgrammaticCritic,
    Rubric,
)
from hmap.agents.refine.integration import (
    CapabilityAdapter,
    RefinementMixin,
    RefineSetup,
    refinable,
    refine_result,
)
from hmap.agents.refine.refiner import Refiner
from hmap.agents.refine.reflexion import ArtifactMemoryStore, InMemoryStore, ReflectionMemory
from hmap.agents.refine.revisers import FullRewriteReviser, SchemaReviser, StrategicReviser, TargetedReviser
from hmap.agents.refine.stop import (
    AllOf,
    AnyOf,
    Budget,
    LoopState,
    MaxIters,
    NoCritical,
    Plateau,
    StopPolicy,
    TestsPass,
    Threshold,
    all_of,
    any_of,
    best_index,
    default_policy,
)
from hmap.agents.refine.taxonomy import IssueClassifier

__all__ = [
    "GENERIC_RUBRIC",
    "AllOf",
    "AnyOf",
    "ArtifactMemoryStore",
    "Attempt",
    "Budget",
    "CapabilityAdapter",
    "CompositeCritic",
    "Criterion",
    "Critic",
    "Critique",
    "FullRewriteReviser",
    "InMemoryStore",
    "Issue",
    "IssueClassifier",
    "LLMRubricCritic",
    "LoopState",
    "MaxIters",
    "NoCritical",
    "Plateau",
    "ProgrammaticCritic",
    "RefineContext",
    "RefineSetup",
    "RefinementMixin",
    "RefinementResult",
    "RefinementSpec",
    "RefinementTrace",
    "Refiner",
    "ReflectionMemory",
    "Reviser",
    "Revision",
    "Rubric",
    "SchemaReviser",
    "StopPolicy",
    "StrategicReviser",
    "TargetedReviser",
    "TestsPass",
    "Threshold",
    "all_of",
    "any_of",
    "best_index",
    "default_policy",
    "refinable",
    "refine_result",
]

"""Critics (Sprint 4 item 4.3): programmatic checks first, an LLM rubric for what code cannot check, and a composite
in which verified findings override the model's opinion."""

from hmap.agents.refine.critics.composite import CAPS, CompositeCritic
from hmap.agents.refine.critics.programmatic import PENALTY, ProgrammaticCritic, score_from_issues
from hmap.agents.refine.critics.rubric import (
    GENERIC_RUBRIC,
    Criterion,
    LLMRubricCritic,
    Rubric,
    RubricAnswer,
    RubricIssue,
)

__all__ = ["CAPS", "GENERIC_RUBRIC", "PENALTY", "CompositeCritic", "Criterion", "LLMRubricCritic",
           "ProgrammaticCritic", "Rubric", "RubricAnswer", "RubricIssue", "score_from_issues"]

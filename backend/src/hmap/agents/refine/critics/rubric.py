"""``LLMRubricCritic``: a model reviews the output criterion by criterion (spec §4, plan D7).

- Runs on ``role="judge"`` — on the cloud a different model family from the producer, which reduces
  self-preference (research.md §4); locally it is the same ``qwen3.5:9b``, so the composite trusts programmatic
  critics first.
- One schema-constrained call: a 1-5 score with a short evidence quote per criterion, then concrete issues. An issue
  must name a location that exists in the material (an id such as ``R3`` / ``T5`` or a path); issues without one
  are dropped — a small model's vague complaints are not actionable.
- Answers are cached by (material, rubric, prompt version) in the loop's cache (plan D10) and by the gateway's
  replay cache, so re-reviewing an unchanged output costs nothing.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from hmap.agents.refine.core import CATEGORIES, Critique, Issue, RefineContext, canonical, digest
from hmap.core.llm.base import Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.rubric")

PROMPT_VERSION = "1"
MAX_ISSUES = 12


@dataclass(frozen=True)
class Criterion:
    id: str
    question: str
    weight: float = 1.0
    category: str = "REQUIREMENT_VIOLATION"   # default category for this criterion's issues


@dataclass(frozen=True)
class Rubric:
    name: str
    subject: str                                  # "a requirement list extracted from a document"
    criteria: tuple[Criterion, ...]
    instructions: str = ""
    version: str = "1"
    location_hint: str = "the id of the item (for example R3)"

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version,
                "criteria": [{"id": c.id, "question": c.question, "weight": c.weight} for c in self.criteria]}


class CriterionScore(BaseModel):
    id: str
    score: int = Field(ge=1, le=5, description="1 = fails the criterion, 5 = fully meets it")
    evidence: str = Field(default="", description="a short quote from the material that supports the score")

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> object:
        if isinstance(value, float):
            value = round(value)
        if isinstance(value, int):
            return max(1, min(5, value))
        return value

    @field_validator("evidence", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return "" if value is None else value


class RubricIssue(BaseModel):
    criterion: str = ""
    category: Literal["FORMAT", "SCHEMA", "OMISSION", "HALLUCINATION", "FACTUAL", "LOGIC", "REQUIREMENT_VIOLATION",
                      "CONSISTENCY", "STYLE", "SAFETY"] = "REQUIREMENT_VIOLATION"
    severity: Literal["minor", "major", "critical"] = "major"
    description: str
    location: str = Field(default="", description="where: an id or path that appears in the material")
    evidence: str = Field(default="", description="a short quote from the material")
    fix_hint: str = Field(default="", description="what to change")

    @field_validator("criterion", "location", "evidence", "fix_hint", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("category", mode="before")
    @classmethod
    def _known_category(cls, value: object) -> object:
        if isinstance(value, str):
            v = value.strip().upper().replace(" ", "_")
            return v if v in CATEGORIES else "REQUIREMENT_VIOLATION"
        return value

    @field_validator("severity", mode="before")
    @classmethod
    def _known_severity(cls, value: object) -> object:
        if isinstance(value, str):
            v = value.strip().lower()
            return v if v in ("minor", "major", "critical") else ("minor" if v == "info" else "major")
        return value


class RubricAnswer(BaseModel):
    criteria: list[CriterionScore] = Field(default_factory=list)
    issues: list[RubricIssue] = Field(default_factory=list)

    @field_validator("criteria", "issues", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value


SYSTEM_PROMPT = """You are a strict but fair reviewer. You review {subject} against a few criteria.

For each criterion give a score from 1 (fails it) to 5 (fully meets it) and quote short evidence from the material.
Then list concrete issues. Each issue:
- criterion: the criterion id;
- category: FORMAT, SCHEMA, OMISSION (something missing), HALLUCINATION (something not supported by the source),
  FACTUAL, LOGIC, REQUIREMENT_VIOLATION, CONSISTENCY, STYLE or SAFETY;
- severity: minor, major or critical;
- description: one sentence;
- location: {location_hint}; it must appear in the material;
- evidence: a short quote from the material that shows the problem;
- fix_hint: what to change.

Rules: judge only what the criteria ask. Never invent a problem: when a criterion is fully met, score it 5 and report
no issue for it. Report each problem once. Reply with the JSON object only."""


def default_render(output: Any, task_input: Any) -> str:
    return canonical(output)


class LLMRubricCritic:
    kind: Literal["programmatic", "llm"] = "llm"

    def __init__(self, rubric: Rubric, *, render: Callable[[Any, Any], str] = default_render,
                 locations: Callable[[Any, Any], Iterable[str]] | None = None, role: str = "judge",
                 name: str | None = None, max_tokens: int = 2000, weight: float = 2.0) -> None:
        """``render(output, task_input)`` is the material shown to the judge (the output plus whatever source it is
        checked against). ``locations(output, task_input)`` lists the valid locations; issues pointing elsewhere are
        dropped."""
        self.rubric = rubric
        self.render = render
        self.locations = locations
        self.role = role
        self.name = name or f"rubric:{rubric.name}"
        self.max_tokens = max_tokens
        self.weight = weight          # in a composite: the judge counts as much as two clean checks by default
        self.dropped: list[str] = []

    def messages(self, material: str) -> list[Message]:
        crit = "\n".join(f"- {c.id}: {c.question}" for c in self.rubric.criteria)
        user = f"Criteria:\n{crit}\n"
        if self.rubric.instructions:
            user += f"\n{self.rubric.instructions}\n"
        user += f"\nMaterial:\n{material}"
        system = SYSTEM_PROMPT.format(subject=self.rubric.subject, location_hint=self.rubric.location_hint)
        return [Message(role="system", content=system), Message(role="user", content=user)]

    async def answer(self, output: Any, task_input: Any, ctx: RefineContext) -> RubricAnswer:
        material = self.render(output, task_input)
        key = "rubric:" + digest(material, self.rubric.describe(), PROMPT_VERSION, self.role)
        if key in ctx.cache:
            return RubricAnswer.model_validate(ctx.cache[key])
        ans = await ctx.generate(self.role, self.messages(material), schema=RubricAnswer,  # type: ignore[arg-type]
                                 max_tokens=self.max_tokens)
        ctx.cache[key] = ans.model_dump(mode="json")
        return ans

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique:
        ans = await self.answer(output, task_input, ctx)
        by_id = {c.id: c for c in self.rubric.criteria}
        weights = scores = 0.0
        for cs in ans.criteria:
            c = by_id.get(cs.id.strip())
            if c is None:
                continue
            weights += c.weight
            scores += c.weight * (cs.score - 1) / 4
        missing = [c for c in self.rubric.criteria if c.id not in {cs.id.strip() for cs in ans.criteria}]
        # a criterion the judge skipped counts as met only if it raised no issue for it
        for c in missing:
            weights += c.weight
            scores += c.weight * (0.5 if any(i.criterion == c.id for i in ans.issues) else 1.0)
        score = round(scores / weights, 4) if weights else 1.0
        valid = {loc.strip() for loc in self.locations(output, task_input)} if self.locations else None
        issues: list[Issue] = []
        self.dropped = []
        for ri in ans.issues[:MAX_ISSUES]:
            loc = ri.location.strip()
            if not loc or (valid is not None and not _location_ok(loc, valid)):
                self.dropped.append(f"no valid location: {ri.description[:80]}")
                continue
            issues.append(Issue(category=ri.category, severity=ri.severity, description=ri.description.strip()
                                or "issue", location=loc, evidence=ri.evidence.strip()[:500] or None,
                                fix_hint=ri.fix_hint.strip()[:300] or None))
        return Critique(score=score, issues=issues, critic=self.name)


def _location_ok(loc: str, valid: set[str]) -> bool:
    """``loc`` names only things that exist: an exact location, a JSON path under a valid path, or a text such as
    ``"T3 -> T5"`` / ``"R2, R4"`` whose every id is valid."""
    if loc in valid:
        return True
    if loc.startswith("/"):
        return any(loc == v or loc.startswith(v.rstrip("/") + "/") for v in valid if v.startswith("/"))
    ids = _ID_RE.findall(loc)
    return bool(ids) and all(i in valid for i in ids)


_ID_RE = re.compile(r"\b(?:[A-Z]{1,3}\d+|research|verify|design|review(?:-v\d+)?)\b")


@dataclass
class RubricSet:
    """Named rubrics (the ``refine.run`` agent picks one by name)."""

    rubrics: dict[str, Rubric] = field(default_factory=dict)

    def get(self, name: str) -> Rubric | None:
        return self.rubrics.get(name)


GENERIC_RUBRIC = Rubric(
    name="generic", subject="a structured result produced by an AI agent",
    criteria=(
        Criterion("G1", "Is the result complete for its objective (nothing important missing)?", 1.0, "OMISSION"),
        Criterion("G2", "Is everything in it supported by the input (nothing invented)?", 1.0, "HALLUCINATION"),
        Criterion("G3", "Is it internally consistent (no contradictions, ids and references match)?", 1.0,
                  "CONSISTENCY"),
        Criterion("G4", "Is it clear and specific enough to act on?", 0.5, "STYLE"),
    ),
    location_hint="a JSON path into the result, for example /sections/2/title")

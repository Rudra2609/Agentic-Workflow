"""``CompositeCritic``: several critics, one critique (spec §4, plan D8).

1. Programmatic critics run first, then LLM critics (an LLM critic is skipped when the loop has no model, and a
   failed LLM call is recorded and skipped — the loop continues on the verified checks alone).
2. **Programmatic issues override LLM opinion:** an LLM issue in a category that a programmatic critic ``covers``
   and found clean is dropped as contradicted; an LLM issue repeating a programmatic one (same category and
   location) is dropped as a duplicate.
3. Score = weighted mean of the critics' scores (a critic's ``weight`` attribute, overridable per name), then
   **capped** by the worst programmatic finding: a critical one caps it at 0.4, a major one at 0.75 — a fluent LLM
   review cannot outvote a failing validator. An open LLM finding caps it more softly (critical 0.6, major 0.85), so a
   loop never reports "good enough" (threshold 0.9) while the judge still points at a major problem.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from hmap.agents.refine.core import Critic, Critique, Issue, RefineContext, max_severity
from hmap.core.errors import Cancelled
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.composite")

CAPS: dict[str, float] = {"critical": 0.4, "major": 0.75}
LLM_CAPS: dict[str, float] = {"critical": 0.6, "major": 0.85}


class CompositeCritic:
    name = "composite"
    kind: Literal["programmatic", "llm"] = "programmatic"

    def __init__(self, critics: Sequence[Critic], *, weights: Mapping[str, float] | None = None,
                 caps: Mapping[str, float] = CAPS, llm_caps: Mapping[str, float] = LLM_CAPS) -> None:
        if not critics:
            raise ValueError("a composite critic needs at least one critic")
        self.critics = list(critics)
        self.weights = dict(weights or {})
        self.caps = dict(caps)
        self.llm_caps = dict(llm_caps)
        self.errors: list[str] = []

    def weight(self, name: str | None) -> float:
        if name in self.weights:
            return self.weights[name or ""]
        critic = next((c for c in self.critics if c.name == name), None)
        return float(getattr(critic, "weight", 1.0))

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.critics]

    async def review_all(self, output: Any, task_input: Any, ctx: RefineContext,
                         errors: list[str] | None = None) -> tuple[Critique, list[Critique]]:
        """The merged critique and each critic's own (for the trace and the judge-agreement metric). LLM critics
        that failed (and were skipped) are appended to ``errors`` (and kept in ``self.errors``)."""
        self.errors = errors if errors is not None else []
        ordered = [c for c in self.critics if c.kind == "programmatic"] + \
            [c for c in self.critics if c.kind != "programmatic"]
        parts: list[Critique] = []
        prog_issues: list[Issue] = []
        clean_categories: set[str] = set()
        for critic in ordered:
            if critic.kind == "llm" and not ctx.has_llm:
                continue
            try:
                part = await critic.review(output, task_input, ctx)
            except Cancelled:
                raise
            except Exception as exc:
                if critic.kind == "programmatic":
                    raise
                self.errors.append(f"{critic.name}: {type(exc).__name__}")
                log.warning("llm critic failed; continuing with the other critics", critic=critic.name,
                            error=type(exc).__name__)
                continue
            part = part.model_copy(update={"critic": part.critic or critic.name})
            if critic.kind == "programmatic":
                prog_issues += part.issues
                found = {i.category for i in part.issues}
                clean_categories |= {c for c in getattr(critic, "covers", ()) if c not in found}
            else:
                # a repeat of a programmatic finding adds nothing — unless it brings evidence (e.g. the missing
                # sentence itself), which the reviser needs
                seen = {(i.category, i.location, i.evidence) for i in prog_issues} | \
                    {(i.category, i.location, None) for i in prog_issues}
                kept = [i for i in part.issues if i.category not in clean_categories
                        and (i.category, i.location, i.evidence) not in seen]
                part = part.model_copy(update={"issues": kept})
            parts.append(part)
        if not parts:
            raise RuntimeError("no critic could review the output")
        total = sum(self.weight(p.critic) for p in parts)
        score = sum(self.weight(p.critic) * p.score for p in parts) / total if total else 1.0
        worst = max_severity(prog_issues)
        if worst in self.caps:
            score = min(score, self.caps[worst])
        issues = [i for p in parts for i in p.issues]
        llm_worst = max_severity([i for i in issues if i not in prog_issues])
        if llm_worst in self.llm_caps:
            score = min(score, self.llm_caps[llm_worst])
        return Critique(score=round(score, 4), issues=issues, critic=self.name), parts

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique:
        merged, _ = await self.review_all(output, task_input, ctx)
        return merged

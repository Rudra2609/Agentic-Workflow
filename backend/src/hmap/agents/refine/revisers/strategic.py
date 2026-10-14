"""Strategy dispatch (items 4.4 + 4.5): one reviser per strategy, chosen by the loop."""

from collections.abc import Sequence
from typing import Any

from hmap.agents.refine.core import Attempt, Critique, RefineContext, Revision, Strategy


class StrategicReviser:
    """Dispatches on the loop's strategy: ``targeted`` first; ``full`` / ``widen`` when Reflexion asks for a
    different approach. A missing strategy falls back to the next broader one, then to ``targeted``."""

    name = "strategic"

    def __init__(self, revisers: dict[str, Any]) -> None:
        if "targeted" not in revisers:
            raise ValueError("a strategic reviser needs a 'targeted' reviser")
        self.revisers = revisers

    def pick(self, strategy: Strategy) -> Any:
        for s in {"widen": ("widen", "full", "targeted"), "full": ("full", "targeted")}.get(strategy, ("targeted",)):
            if s in self.revisers:
                return self.revisers[s]
        return self.revisers["targeted"]

    async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: Any = None, strategy: Strategy = "targeted") -> Revision:
        reviser = self.pick(strategy)
        rev: Revision = await reviser.revise(output, critique, history, ctx, task_input=task_input,
                                             strategy=strategy)
        rev.notes = [f"strategy: {strategy} ({getattr(reviser, 'name', 'reviser')})", *rev.notes]
        return rev

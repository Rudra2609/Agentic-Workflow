"""Revisers (Sprint 4 item 4.4): targeted patch, full rewrite, schema-constrained rewrite, and a dispatcher that
picks one by the loop's strategy (Reflexion changes it after repeated failures).

``TargetedReviser`` asks the model for JSON-pointer patches and applies **only** those inside the locations the
critique flagged (an omission flagged at ``/requirements`` may append ``/requirements/-``). Everything else stays
byte-identical; an optional ``guard`` refuses domain-invalid patches (an added item whose quote is not in the
document, a dependency that would make a cycle) and ``validate`` refuses a result that breaks the contract — then
the reviser returns the old output and says why.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from hmap.agents.refine.core import Attempt, Critique, RefineContext, Revision, Strategy, to_jsonable
from hmap.agents.refine.revisers.patch import Patch, PatchError, apply, within
from hmap.core.llm.base import Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.reviser")

PROMPT_VERSION = "1"
MAX_PATCHES = 20


def issue_lines(critique: Critique) -> str:
    return "\n".join(
        f"{n}. [{i.severity} {i.category}] at {i.location or '-'}: {i.description}"
        + (f" (evidence: {i.evidence[:160]})" if i.evidence else "")
        + (f" (fix: {i.fix_hint[:160]})" if i.fix_hint else "")
        for n, i in enumerate(critique.issues, start=1))


def reflection_lines(history: Sequence[Attempt], ctx: RefineContext) -> str:
    """Reflexion: notes written after earlier failed attempts of this loop, plus remembered notes from earlier
    runs of similar tasks in the same project."""
    notes = [a.reflection for a in history if a.reflection]
    memory = getattr(ctx.memory, "remembered", None)
    if callable(memory):
        notes = [*memory(), *notes]
    return "\n".join(f"- {n}" for n in notes[-6:])


class PatchOp(BaseModel):
    op: Literal["add", "replace", "remove"]
    path: str
    value_json: str = Field(default="", description="the new value as JSON text (empty for remove)")
    issue: int | None = Field(default=None, description="number of the issue this fixes")

    @field_validator("value_json", "path", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        if value is None:
            return ""
        return value if isinstance(value, str) else json.dumps(value)


class PatchAnswer(BaseModel):
    patches: list[PatchOp] = Field(default_factory=list)
    notes: str = ""

    @field_validator("patches", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("notes", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value


TARGETED_PROMPT = """You fix a structured result. You get the result as JSON, the issues a reviewer found (each with a
location: a JSON path into the result), and notes from earlier attempts.

Return {"patches": [...], "notes": "..."} where each patch is
{"op": "replace" | "add" | "remove", "path": "<JSON path>", "value_json": "<the new value as JSON text>",
 "issue": <issue number>}.

Rules:
- Only change what an issue points at: the path must be the issue's location or inside it. To add an item to a list
  named by an issue, use the list's path followed by "/-".
- Keep everything else exactly as it is. Do the smallest change that fixes the issue.
- Never invent facts that the input does not support. If an issue is wrong, skip it and say so in notes."""




class TargetedReviser:
    name = "targeted"

    def __init__(self, *, render_input: Callable[[Any], str] | None = None,
                 load: Callable[[Any], Any] | None = None,
                 guard: Callable[[Patch, Any, Any], str | None] | None = None,
                 validate: Callable[[Any], Any] | None = None, role: str | None = None,
                 max_tokens: int = 2500) -> None:
        """``load(json_value)`` turns the patched JSON back into the output type (e.g. ``Model.model_validate``) and
        doubles as validation. ``render_input(task_input)`` is the source context shown to the model."""
        self.render_input = render_input
        self.load = load
        self.guard = guard
        self.validate = validate
        self.role = role
        self.max_tokens = max_tokens

    async def propose(self, doc: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext,
                      task_input: Any, strategy: Strategy) -> PatchAnswer:
        parts = [f"Issues:\n{issue_lines(critique)}"]
        if notes := reflection_lines(history, ctx):
            parts.append(f"Notes from earlier attempts:\n{notes}")
        if strategy != "targeted":
            parts.append("Earlier targeted fixes did not solve these issues: look at the whole result, not only the "
                         "flagged paths, and fix the cause.")
        if self.render_input is not None and task_input is not None:
            parts.append(f"Input:\n{self.render_input(task_input)}")
        parts.append(f"Result:\n{json.dumps(doc, indent=1, ensure_ascii=False)}")
        messages = [Message(role="system", content=TARGETED_PROMPT), Message(role="user", content="\n\n".join(parts))]
        return await ctx.generate(self.role or ctx.reviser_role, messages, schema=PatchAnswer,  # type: ignore[arg-type]
                                  max_tokens=self.max_tokens)

    async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: Any = None, strategy: Strategy = "targeted") -> Revision:
        doc = to_jsonable(output)
        answer = await self.propose(doc, critique, history, ctx, task_input, strategy)
        scopes = [i.location for i in critique.issues if i.location and i.location.startswith("/")]
        if strategy != "targeted":
            scopes = [""]                      # full / widen: the whole document may change
        new, applied, rejected = doc, 0, []
        for op in answer.patches[:MAX_PATCHES]:
            target = op.path[:-2] if op.path.endswith("/-") else op.path
            if not any(within(target, s) or within(op.path, s) for s in scopes):
                rejected.append(f"{op.op} {op.path}: outside the flagged locations")
                continue
            try:
                value = json.loads(op.value_json) if op.op != "remove" else None
            except json.JSONDecodeError:
                rejected.append(f"{op.op} {op.path}: value is not JSON")
                continue
            patch = Patch(op.op, op.path, value)
            if self.guard is not None and (why := self.guard(patch, new, task_input)):
                rejected.append(f"{op.op} {op.path}: {why}")
                continue
            try:
                new = apply(new, patch)
                applied += 1
            except PatchError as exc:
                rejected.append(f"{op.op} {op.path}: {exc}")
        result: Any = new
        if applied and self.load is not None:
            try:
                result = self.load(new)
            except Exception as exc:
                log.info("patched result rejected by the contract", error=type(exc).__name__)
                return Revision(output=output, notes=[answer.notes] if answer.notes else [], applied=0,
                                rejected=[*rejected, f"the patched result breaks the contract: {str(exc)[:200]}"])
        elif not applied:
            result = output
        if applied and self.validate is not None and (why := self.validate(result)):
            return Revision(output=output, applied=0, rejected=[*rejected, f"refused: {why}"])
        return Revision(output=result, notes=[answer.notes] if answer.notes else [], applied=applied,
                        rejected=rejected)

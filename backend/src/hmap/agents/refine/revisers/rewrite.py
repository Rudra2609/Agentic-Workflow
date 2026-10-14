"""Full-rewrite and constrained-schema revisers (item 4.4): used when targeted patches keep failing (Reflexion's
strategy change) or for outputs without stable locations."""

import json
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from hmap.agents.refine.core import Attempt, Critique, RefineContext, Revision, Strategy, to_jsonable
from hmap.agents.refine.revisers.targeted import issue_lines, reflection_lines
from hmap.core.llm.base import Message

REWRITE_PROMPT = """You rewrite a structured result so that it fixes every issue a reviewer found, using the notes
from earlier attempts. Keep everything that was right. Never invent facts that the input does not support. Reply
with the complete corrected result as JSON."""


class FullRewriteReviser:
    """Asks for the whole corrected result (``schema`` constrains it). Used when targeted fixes keep failing."""

    name = "full_rewrite"

    def __init__(self, schema: type[BaseModel], *, render_input: Callable[[Any], str] | None = None,
                 role: str | None = None, max_tokens: int = 4000,
                 validate: Callable[[Any], str | None] | None = None) -> None:
        self.schema = schema
        self.render_input = render_input
        self.role = role
        self.max_tokens = max_tokens
        self.validate = validate

    async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: Any = None, strategy: Strategy = "full") -> Revision:
        parts = [f"Issues:\n{issue_lines(critique)}"]
        if notes := reflection_lines(history, ctx):
            parts.append(f"Notes from earlier attempts:\n{notes}")
        if self.render_input is not None and task_input is not None:
            parts.append(f"Input:\n{self.render_input(task_input)}")
        parts.append(f"Result:\n{json.dumps(to_jsonable(output), indent=1, ensure_ascii=False)}")
        messages = [Message(role="system", content=REWRITE_PROMPT), Message(role="user", content="\n\n".join(parts))]
        new = await ctx.generate(self.role or ctx.reviser_role, messages, schema=self.schema,  # type: ignore[arg-type]
                                 max_tokens=self.max_tokens)
        if self.validate is not None and (why := self.validate(new)):
            return Revision(output=output, applied=0, rejected=[f"rewrite refused: {why}"])
        return Revision(output=new, notes=["rewrote the whole result"], applied=1)


class SchemaReviser(FullRewriteReviser):
    """Constrained-schema reviser: the rewrite is generated against the contract's JSON Schema (the gateway repairs
    invalid JSON up to twice) and must validate as ``schema``; otherwise the old output is kept."""

    name = "schema"

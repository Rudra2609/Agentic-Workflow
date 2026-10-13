"""LLM extraction per chunk (spec item 2.5): one schema-constrained ``reasoner`` call, the rule hits as hints, the
answer cached by chunk text + prompt version. Items whose quote cannot be found get one targeted re-ask (item 2.7).
"""

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from hmap.agents.doc_intel.cache import ResultCache, cache_key
from hmap.agents.doc_intel.chunking import Chunk
from hmap.agents.doc_intel.extract.quotes import locate
from hmap.agents.doc_intel.extract.rules import RuleHit
from hmap.core.llm.base import LLMClient, Message

PROMPT_VERSION = "3"
TEMPERATURE = 0.0
SEED = 7
MAX_TOKENS = 3000


class ExtractedItem(BaseModel):
    kind: Literal["requirement", "constraint", "deliverable"]
    text: str = Field(description="the item as one clear sentence, close to the source wording")
    quote: str = Field(description="the exact source sentence, copied character for character")
    priority: Literal["must", "should", "could"] = "must"
    req_type: Literal["functional", "non_functional"] = "functional"
    constraint_kind: Literal["technology", "format", "process", "resource", "other"] = "other"
    deliverable_name: str = ""
    deliverable_format: str = ""

    @field_validator("priority", "req_type", "constraint_kind", "deliverable_name", "deliverable_format",
                     mode="before")
    @classmethod
    def _null_means_default(cls, value: object, info: object) -> object:
        """Models often write null for a field that does not apply (a requirement's constraint_kind): use the
        default instead of failing the whole answer."""
        if value is None:
            name = getattr(info, "field_name", "")
            return cls.model_fields[name].default
        return value


class ChunkExtraction(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You extract requirements from a course assignment, lab sheet or project brief.

Return JSON with "items" and "open_questions". Each item:
- kind: "requirement" = something the solution or the work must do or be: a feature, a behaviour, a task to carry
  out, or a quality such as speed, reliability, usability, security, test quality. It may name a tool or a format
  ("Draw an ER diagram", "Each test must check one behaviour", "The schema must be in third normal form").
  "constraint" = a limit on how or with what you work: programming language, libraries, framework or version, team
  size, deadline, page or time limits, things you must not change, reusing the result of another part.
  "deliverable" = something to hand in ("Submit X as a PDF" is the deliverable X, format PDF).
- text: the item as one clear sentence, close to the source wording.
- quote: the exact source sentence or list item, copied character for character from the text.
- priority: "must" (must, shall, required, or a plain instruction), "should" (should, recommended),
  "could" (may, could, optional, extra credit).
- req_type: "functional" or "non_functional" (performance, reliability, usability, security, code quality).
- constraint_kind: technology, format, process, resource or other.
- deliverable_name and deliverable_format: a short name and the file format, for deliverables.

Rules:
- One item per sentence or list item. Never merge two sentences or split one.
- A sentence ending with ":" that introduces a list ("At minimum, your code needs to support:") is not an item.
  Each list item under it is one, with the lead-in's kind and priority, written as a full sentence ("The code must
  support booking confirmation."); quote the list item itself.
- Only use what the text says. Never invent requirements, numbers or file formats.
- Skip background, motivation, reading instructions, and setup steps that are not marked or checked.
- Marking tables and footnotes are handled elsewhere: do not turn them into items.
- open_questions: short questions about anything ambiguous or contradictory (an empty list if nothing is unclear)."""


def build_messages(chunk: Chunk, hints: list[RuleHit]) -> list[Message]:
    user = chunk.text
    if hints:
        listed = "\n".join(f"- {h.text}" for h in hints[:40])
        user += ("\n\nSentences that contain requirement keywords (a hint only: some may not be items, and items "
                 f"may be missing):\n{listed}")
    return [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content=user)]


def _reask_messages(chunk: Chunk, items: list[ExtractedItem]) -> list[Message]:
    listed = "\n".join(f"- {it.quote!r} ({it.kind}: {it.text})" for it in items)
    return [Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=f"{chunk.text}\n\nThese quotes are not in the text above:\n{listed}\n\n"
                                         "For each item, copy the exact sentence from the text as its quote, or "
                                         "leave the item out if the text does not say it.")]


async def extract_chunk(llm: LLMClient, chunk: Chunk, hints: list[RuleHit],
                        cache: ResultCache | None = None) -> tuple[ChunkExtraction, str]:
    """The extraction and who answered it: ``provider:model`` (``cache:<model>`` when replayed), or ``memory`` when
    this agent had already extracted the same chunk."""
    key = cache_key("extract", PROMPT_VERSION, chunk.text, "\n".join(h.text for h in hints))
    if cache is not None and (hit := await cache.get(key)) is not None:
        return ChunkExtraction.model_validate_json(hit), "memory"
    resp = await llm.generate("reasoner", build_messages(chunk, hints), schema=ChunkExtraction,
                              temperature=TEMPERATURE, max_tokens=MAX_TOKENS, seed=SEED)
    result: ChunkExtraction = resp.parsed
    answered_by = f"{resp.usage.provider or 'unknown'}:{resp.usage.model or 'unknown'}"
    missing = [it for it in result.items if locate(it.quote, chunk.blocks).status == "unverified"]
    if missing:
        fixed: ChunkExtraction = (await llm.generate("reasoner", _reask_messages(chunk, missing),
                                                     schema=ChunkExtraction, temperature=TEMPERATURE,
                                                     max_tokens=MAX_TOKENS, seed=SEED)).parsed
        keep = [it for it in result.items if it not in missing]
        result = ChunkExtraction(items=keep + fixed.items,
                                 open_questions=result.open_questions + fixed.open_questions)
    if cache is not None:
        await cache.put(key, json.dumps(result.model_dump(mode="json")))
    return result, answered_by

"""L2 — does the quoted text support the claim? (Sprint 6 item 6.3)

A model on role ``judge`` (on the cloud a different model family from the researcher's ``reasoner``; doc 02 §2.5)
sees **only** the claim and the quoted passages — not the research brief, the queries or the report — and answers a
constrained verdict ``supports | refutes | not_enough`` with a one-sentence rationale.

Bias controls:
- **position:** the same question is asked a second time with the passages first and the claim last; when the two
  answers differ the judgement is *unsure* (the aggregator says NEEDS_MORE_RESEARCH);
- **verbosity:** inputs are short and capped (quotes ≤ 600 characters each, at most 4), the answer is an enum;
- **number guard (rules):** if the claim states a number the passages never mention, a "supports" becomes
  "not_enough" — a changed figure is the commonest planted and natural error.

The passages are untrusted page text, wrapped like Member 5's prompts (``sanitize.wrap``). Without a model (fake
mode, an error, no key and no local model) a word-overlap rule decides and the judgement is marked ``by="rules"``.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from hmap.agents.research import sanitize
from hmap.agents.verify import textual
from hmap.agents.verify.model import Judgement, Label
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.verify.entail")
PROMPT_VERSION = "1"
MAX_PASSAGES = 4
MAX_PASSAGE_CHARS = 600
SUPPORT_OVERLAP = 0.75


class EntailAnswer(BaseModel):
    rationale: str = Field(default="", description="one short sentence: what the passages say about the claim")
    verdict: Literal["supports", "refutes", "not_enough"] = Field(
        description="supports = the passages state the claim, including its numbers, names and conditions; "
                    "refutes = the passages state something that cannot be true together with the claim; "
                    "not_enough = related, but the passages do not state the claim (or it adds details they lack)")


SYSTEM = ("You are a strict fact checker. Decide whether the quoted source passages support a claim. Judge only by "
          "what the passages say, not by what you know. A claim is supported only if every part of it - numbers, "
          "names, versions, conditions, comparisons - is stated in the passages; a claim that goes further than "
          "the passages is not_enough. " + sanitize.UNTRUSTED_NOTE + " Answer in JSON.")


@dataclass
class Usage:
    calls: int = 0
    tokens: int = 0
    errors: list[str] = field(default_factory=list)


def _passages_block(passages: Sequence[tuple[str, str]]) -> str:
    return "\n\n".join(sanitize.wrap(text[:MAX_PASSAGE_CHARS], source=src) for src, text in passages[:MAX_PASSAGES])


def messages(claim: str, passages: Sequence[tuple[str, str]], *, swapped: bool = False) -> list[dict[str, str]]:
    block = _passages_block(passages)
    if swapped:
        user = f"Source passages:\n{block}\n\nClaim: {claim}\n\nDo the passages support the claim?"
    else:
        user = f"Claim: {claim}\n\nSource passages:\n{block}\n\nDo the passages support the claim?"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def rules_label(claim: str, passages: Sequence[tuple[str, str]]) -> tuple[Label, str]:
    text = " ".join(t for _, t in passages)
    missing = textual.missing_numbers(claim, text)
    if missing:
        return "not_enough", f"the passages do not mention {', '.join(sorted(missing))}"
    cov = textual.overlap(claim, text)
    if cov >= SUPPORT_OVERLAP:
        return "supports", f"the passages contain {cov:.0%} of the claim's content words"
    return "not_enough", f"the passages contain only {cov:.0%} of the claim's content words"


async def _ask(llm: LLMClient, claim: str, passages: Sequence[tuple[str, str]], swapped: bool,
               usage: Usage) -> EntailAnswer:
    resp = await llm.generate("judge", messages(claim, passages, swapped=swapped), schema=EntailAnswer,
                              max_tokens=300, temperature=0.0)
    usage.calls += 1
    usage.tokens += resp.usage.input_tokens + resp.usage.output_tokens
    parsed = resp.parsed
    return parsed if isinstance(parsed, EntailAnswer) else EntailAnswer.model_validate(parsed)


def guard(claim: str, passages: Sequence[tuple[str, str]], label: Label) -> tuple[Label, str]:
    if label != "supports":
        return label, ""
    missing = textual.missing_numbers(claim, " ".join(t for _, t in passages))
    if missing:
        return "not_enough", f"number guard: the passages do not mention {', '.join(sorted(missing))}"
    return label, ""


async def judge(llm: LLMClient | None, claim: str, passages: Sequence[tuple[str, str]], *, swap: bool = True,
                use_guard: bool = True, usage: Usage | None = None) -> Judgement:
    """One judgement of ``claim`` against ``passages`` [(source, text)]."""
    usage = usage if usage is not None else Usage()
    if not passages:
        return Judgement(label="not_enough", rationale="no passage to check against", by="rules")
    if llm is None:
        ruled, why = rules_label(claim, passages)
        return Judgement(label=ruled, rationale=why, by="rules")
    try:
        first = await _ask(llm, claim, passages, False, usage)
        second = await _ask(llm, claim, passages, True, usage) if swap else None
    except Cancelled:
        raise
    except Exception as exc:  # no model / unparsable answer: the rules decide, visibly
        usage.errors.append(type(exc).__name__)
        log.info("judge unavailable, rules decide", error=type(exc).__name__)
        fallback, why = rules_label(claim, passages)
        return Judgement(label=fallback, rationale=why, by="rules")
    label: Label = first.verdict
    note = ""
    if use_guard:
        label, note = guard(claim, passages, label)
    swapped: Label | None = None
    if second is not None:
        swapped = guard(claim, passages, second.verdict)[0] if use_guard else second.verdict
    return Judgement(label=label, rationale=first.rationale.strip()[:400], by="model", swapped_label=swapped,
                     guard=note)

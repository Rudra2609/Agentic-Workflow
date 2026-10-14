"""Research planner (Sprint 5 item 5.1): brief questions -> sub-questions, 2-3 search queries each, and what would
count as answered. One ``reasoner`` call (schema); a rule fallback without a model. Checked in code: every brief
question gets at least one sub-question, ids are unique, queries are short plain text (no URLs, no operators)."""

import re

from pydantic import BaseModel, Field, field_validator

from hmap.agents.research.corpus import tokens
from hmap.core.contracts import ResearchBrief
from hmap.core.contracts.domain import SubQuestion
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.research.planner")
PROMPT_VERSION = "1"
MAX_SUB_QUESTIONS = 4          # per brief question
MAX_QUERIES = 3


class DraftSubQuestion(BaseModel):
    question: int = Field(description="index (0-based) of the brief question this belongs to")
    text: str = Field(description="one specific, answerable sub-question")
    queries: list[str] = Field(description="2-3 short web search queries (plain words, no quotes or operators)")
    success_criteria: str = Field(default="", description="what an answer must contain, in one sentence")

    @field_validator("queries", mode="before")
    @classmethod
    def _list(cls, v: object) -> object:
        return [v] if isinstance(v, str) else v


class PlanAnswer(BaseModel):
    sub_questions: list[DraftSubQuestion]


SYSTEM = (
    "You plan web research for a student software project. Split each question into 1-4 specific sub-questions "
    "that a few web pages can answer (definitions, how something works, trade-offs, limits, typical numbers). "
    "For each give 2-3 short search queries in plain words (3-8 words, no quotes, no site: or other operators) and "
    "one sentence saying what a good answer must contain. Stay on the questions; do not add unrelated topics.")


def _clean_query(q: str) -> str:
    q = re.sub(r"https?://\S+", " ", q)
    q = re.sub(r"\b(site|inurl|intitle|filetype):\S*", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"[\"'`()\[\]{}<>|*]", " ", q)
    return " ".join(q.split())[:120]


def rule_plan(brief: ResearchBrief) -> list[SubQuestion]:
    """Without a model: one sub-question per brief question; queries = the question, its key words, and its key
    words with the scope's key words."""
    scope = " ".join(tokens(brief.scope)[:4])
    out: list[SubQuestion] = []
    for n, q in enumerate(brief.questions):
        key = " ".join(tokens(q)[:8])
        queries = [_clean_query(q), key] + ([f"{key} {scope}".strip()] if scope else [])
        out.append(SubQuestion(id=f"S{n + 1}.1", question=n, text=q.strip(), queries=_dedup(queries),
                               success_criteria="the question is answered with at least two sourced facts"))
    return out


def _dedup(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        k = " ".join(q.lower().split())
        if q and k not in seen:
            seen.add(k)
            out.append(q)
    return out[:MAX_QUERIES]


def finalise(brief: ResearchBrief, drafts: list[DraftSubQuestion]) -> list[SubQuestion]:
    per_q: dict[int, list[SubQuestion]] = {}
    for d in drafts:
        if not (0 <= d.question < len(brief.questions)) or not d.text.strip():
            continue
        subs = per_q.setdefault(d.question, [])
        if len(subs) >= MAX_SUB_QUESTIONS:
            continue
        queries = _dedup([_clean_query(q) for q in d.queries if _clean_query(q)])
        if not queries:
            queries = [_clean_query(d.text)]
        subs.append(SubQuestion(id=f"S{d.question + 1}.{len(subs) + 1}", question=d.question, text=d.text.strip(),
                                queries=queries, success_criteria=d.success_criteria.strip()[:300]))
    fallback = {s.question: s for s in rule_plan(brief)}
    out: list[SubQuestion] = []
    for n in range(len(brief.questions)):          # every brief question is covered by at least one sub-question
        out += per_q.get(n) or [fallback[n]]
    return out


async def plan(brief: ResearchBrief, llm: LLMClient | None) -> tuple[list[SubQuestion], str]:
    """(sub-questions, "model" | "rules")."""
    if llm is None:
        return rule_plan(brief), "rules"
    lines = [f"{n}. {q}" for n, q in enumerate(brief.questions)]
    user = "Questions:\n" + "\n".join(lines)
    if brief.scope:
        user += f"\n\nProject context (for relevance only): {brief.scope[:600]}"
    if brief.constraints:
        user += "\n\nConstraints of the project: " + "; ".join(c[:150] for c in brief.constraints[:6])
    try:
        resp = await llm.generate("reasoner", [{"role": "system", "content": SYSTEM},
                                               {"role": "user", "content": user}], schema=PlanAnswer,
                                  max_tokens=1500, temperature=0.2)
        answer: PlanAnswer = resp.parsed
    except Exception as exc:
        from hmap.core.errors import Cancelled

        if isinstance(exc, Cancelled):
            raise
        log.info("research planner fell back to rules", error=type(exc).__name__)
        return rule_plan(brief), "rules"
    return finalise(brief, answer.sub_questions), "model"

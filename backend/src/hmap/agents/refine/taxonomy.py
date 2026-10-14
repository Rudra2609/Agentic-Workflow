"""Error taxonomy (Sprint 4 item 4.7): every issue gets one of 10 categories x 4 severities.

    FORMAT, SCHEMA, OMISSION, HALLUCINATION, FACTUAL, LOGIC, REQUIREMENT_VIOLATION, CONSISTENCY, STYLE, SAFETY
    x  info, minor, major, critical

Rules first (a validator's issue code, then wording patterns); the model (``ctx.llm.classify``, role ``classify``)
only for free-text issues no rule recognises. A programmatic critic's category is trusted as is; an LLM critic's own
label is used when neither rules nor ``classify`` are available. Every decision is kept
(:class:`Classification`: the text, the rule label, the model label, the critic label and the final one) — labelled
data for Member 11's classifier (Sprint 11); accuracy on ``samples/refine/taxonomy_gold.jsonl`` is in eval.md.
"""

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from hmap.agents.refine.core import CATEGORIES, SEVERITIES, Issue, RefineContext
from hmap.core.errors import Cancelled
from hmap.core.llm.base import ClassifyQuestion
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.taxonomy")

DEFINITIONS: dict[str, str] = {
    "FORMAT": "the output is not well-formed (unparseable JSON, broken markup, wrong layout)",
    "SCHEMA": "a field is missing, has the wrong type or breaks the contract / allowed values",
    "OMISSION": "something that should be there is missing (a requirement, a step, a criterion, a section)",
    "HALLUCINATION": "something is not supported by the source (invented item, quote not in the document)",
    "FACTUAL": "a stated fact, number, date, name or attribute (priority, kind, type) is wrong",
    "LOGIC": "the reasoning or structure is wrong (cycle, wrong order, missing dependency, impossible plan)",
    "REQUIREMENT_VIOLATION": "the output does not meet a stated requirement or acceptance criterion",
    "CONSISTENCY": "parts disagree with each other (duplicates, totals that do not add up, mismatched ids)",
    "STYLE": "unclear, vague, untestable or badly worded, but not wrong",
    "SAFETY": "unsafe content, leaked secrets or personal data, harmful instructions",
}

# Issue codes of the programmatic critics (Member 3's validator, our own checks) -> category.
CODE_RULES: dict[str, str] = {
    "cycle": "LOGIC", "self_dependency": "LOGIC", "multiple_sinks": "LOGIC", "sink_not_review": "LOGIC",
    "orphan": "LOGIC", "unjustified": "LOGIC", "missing_dependency": "LOGIC",
    "unknown_dependency": "CONSISTENCY", "duplicate_id": "CONSISTENCY", "duplicate_title": "CONSISTENCY",
    "capability_phase": "CONSISTENCY", "marks_sum_mismatch": "CONSISTENCY", "duplicate_item": "CONSISTENCY",
    "uncovered": "REQUIREMENT_VIOLATION", "unknown_capability": "SCHEMA", "invalid_contract": "SCHEMA",
    "no_acceptance": "OMISSION", "empty": "OMISSION", "no_requirements": "OMISSION", "missed_sentence": "OMISSION",
    "unknown_requirement": "HALLUCINATION", "quote_not_found": "HALLUCINATION", "no_quote": "HALLUCINATION",
    "too_many_tasks": "STYLE", "vague_criterion": "STYLE", "empty_title": "FORMAT", "invalid_json": "FORMAT",
    "secret": "SAFETY",
}

# Wording patterns, most specific first. The first match wins.
TEXT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("SAFETY", re.compile(r"\b(api[ _-]?keys?|passwords?|secrets?|token leak|real names|email addresses|"
                          r"personal data (?:is|are) (?:exposed|logged|leaked|included)|unsafe|harmful|injection|"
                          r"deletes? (?:the |all )?(?:home|files|data))\b", re.I)),
    ("FORMAT", re.compile(r"\b(not valid json|invalid json|unparseable|cannot be parsed|could not be parsed|malformed|"
                          r"syntax error|trailing comma|broken (?:markup|format|table)|table is broken|"
                          r"iso format)\b", re.I)),
    ("LOGIC", re.compile(r"\b(cycle|circular|depends? on itself|depends? (?:only )?on|does not depend on|"
                         r"dependenc(?:y|ies)|must (?:come|run|happen) (?:before|after)|should come (?:before|after)|"
                         r"runs? (?:before|after)|scheduled to run|waits? for|needs? the (?:output|result) of|"
                         r"wrong order|ordering|unreachable|orphan|has no predecessor|race condition|ends in two)\b",
                         re.I)),
    ("HALLUCINATION", re.compile(r"\b(not (?:found |stated |mentioned )?in the (?:document|source|text|input)|"
                                 r"not supported by|unsupported|invent(?:ed|s)?|fabricat\w*|hallucinat\w*|"
                                 r"no such (?:requirement|item)|does not appear|cannot be found|not among the sources|"
                                 r"quote (?:is )?not found|unverified quote|made up|background information|"
                                 r"(?:reading|process) instruction|not an item|refers to .{0,40}(?:but|which) .{0,40}"
                                 r"(?:ends|does not exist))\b", re.I)),
    ("SCHEMA", re.compile(r"\b(schema|required field|missing field|field \w+ is missing|wrong type|"
                          r"not an allowed value|invalid value|contract|unknown capability|not one of|"
                          r"requires? a (?:number|list|string)|must be a (?:list|number|string)|does not validate)\b",
                          re.I)),
    ("CONSISTENCY", re.compile(r"\b(duplicat\w*|inconsisten\w*|mismatch\w*|contradict\w*|do(?:es)? not add up|"
                               r"add(?:s)? up to|sum(?:s)? to|twice|repeated|conflicting|same (?:title|thing|name)|"
                               r"while the \w+ (?:has|shows|lists)|but the \w+ shows)\b", re.I)),
    ("REQUIREMENT_VIOLATION", re.compile(r"\b(violat\w*|does not (?:meet|satisfy|follow|cover)|not covered|"
                                         r"is not met|are not met|forbids?|must not be (?:modified|changed|used)|"
                                         r"the limit is|exceeds the limit|requirement .{0,40}not met|"
                                         r"fails? (?:the|a) requirement)\b", re.I)),
    ("FACTUAL", re.compile(r"\b(incorrect (?:number|value|date|name|total|priority|kind|type)|wrong (?:number|value|"
                           r"date|name|total|fact|priority|kind|type)|is wrong|factual\w*|inaccurate|misstat\w*|"
                           r"priority (?:is|should be)|has priority|marked as|labell?ed|stated as|"
                           r"should be (?:a |an )?(?:constraint|deliverable|requirement|must|should|could|functional|"
                           r"non.functional)|(?:is|was) (?:classified|marked) as|it is \w+ that)\b", re.I)),
    ("OMISSION", re.compile(r"\b(missing|missed|omit\w*|not (?:listed|included|extracted|captured|planned)|absent|"
                            r"lacks?|leaves? out|left out|no step (?:for|covers)|there is no|has no|is not listed)\b",
                            re.I)),
    ("STYLE", re.compile(r"\b(vague|unclear|ambiguous wording|not testable|untestable|cannot be checked|"
                         r"not (?:concrete|checkable)|wording|verbose|too long|shorten|typo|style|could be clearer|"
                         r"over-?split|too fine|too granular|for no reason)\b", re.I)),
]

QUESTION = "category"


@dataclass
class Classification:
    """One taxonomy decision (kept in the trace; labelled data for Sprint 11)."""

    text: str
    critic_label: str | None
    rule: str | None
    rule_label: str | None
    llm_label: str | None
    final: str
    source: str                   # programmatic | rule | classify | critic

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def rule_label(text: str, code: str | None = None) -> tuple[str | None, str | None]:
    """(category, rule name) from an issue code or the wording; (None, None) when no rule applies."""
    if code and code in CODE_RULES:
        return CODE_RULES[code], f"code:{code}"
    for category, pattern in TEXT_RULES:
        if pattern.search(text):
            return category, f"text:{category.lower()}"
    return None, None


def issue_text(issue: Issue) -> str:
    return issue.description + (f" Evidence: {issue.evidence}" if issue.evidence else "")


def question() -> ClassifyQuestion:
    return ClassifyQuestion(name=QUESTION, kind="choice", options=list(CATEGORIES), criteria=dict(DEFINITIONS))


class IssueClassifier:
    """``classify(issues, ctx, programmatic=...)`` returns the issues with final categories and the decisions."""

    def __init__(self, *, use_llm: bool = True) -> None:
        self.use_llm = use_llm

    async def classify(self, issues: Sequence[Issue], ctx: RefineContext, *, programmatic: bool = False,
                       codes: Sequence[str | None] | None = None) -> tuple[list[Issue], list[Classification]]:
        out: list[Issue] = []
        decisions: list[Classification] = []
        for n, issue in enumerate(issues):
            code = codes[n] if codes is not None and n < len(codes) else None
            text = issue_text(issue)
            label, rule = rule_label(issue.description, code)
            llm_label: str | None = None
            final: str
            if programmatic:
                final, source = issue.category, "programmatic"
            elif label is not None:
                final, source = label, "rule"
            elif self.use_llm and ctx.has_llm:
                try:
                    [answer] = await ctx.classify(text[:600], [question()])
                    llm_label = answer.answer if answer.answer in CATEGORIES else None
                except Cancelled:
                    raise
                except Exception as exc:
                    log.info("classify failed; keeping the critic's label", error=type(exc).__name__)
                final, source = (llm_label, "classify") if llm_label else (issue.category, "critic")
            else:
                final, source = issue.category, "critic"
            decisions.append(Classification(text=text[:400], critic_label=issue.category, rule=rule,
                                            rule_label=label, llm_label=llm_label, final=final, source=source))
            out.append(issue if final == issue.category else Issue.model_validate(
                {**issue.model_dump(), "category": final}))
        return out, decisions


def severity_ok(severity: str) -> bool:
    return severity in SEVERITIES

"""Refine loop for the documents (Sprint 9 item 9.9, plan D9), on Member 4's ``Refiner``.

    critics : GroundingCritic (programmatic: the rule checker + behaviour verdicts + failed examples; its issues
              are facts and win) and CompletenessCritic (``reasoner``: required sections / deliverables missing)
    reviser : SentenceReviser: each ungrounded sentence is rewritten by ``reasoner`` from the facts or deleted;
              without a model it is deleted
    stop    : any_of(Threshold(1.0), MaxIters(HMAP_DOCGEN_MAX_ROUNDS), Plateau)

Then the **final gate**: whatever is still ungrounded is removed from the shipped document and kept in the
accuracy report (``Accuracy.removed``). A document never ships with a claim the code contradicts.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from hmap.agents.docgen.grounding import Checker, remove_sentences, summarize
from hmap.agents.docgen.model import Accuracy, Claim, ExampleResult, Facts
from hmap.agents.docgen.summarize import UNTRUSTED
from hmap.agents.refine.core import Attempt, Critique, Issue, RefineContext, Revision
from hmap.agents.refine.critics.programmatic import ProgrammaticCritic
from hmap.agents.refine.refiner import Refiner
from hmap.agents.refine.stop import MaxIters, Plateau, Threshold, any_of
from hmap.agents.refine.taxonomy import IssueClassifier
from hmap.core.llm.base import Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.docgen.refine")

Docs = dict[str, str]


@dataclass
class DocInput:
    facts: Facts
    required: dict[str, list[str]]                      # doc -> headings it must have
    deliverables: list[str] = field(default_factory=list)
    behaviour_bad: list[Claim] = field(default_factory=list)   # CONTRADICTED by the model layer (checked once)
    examples: list[ExampleResult] = field(default_factory=list)
    extra: list[Claim] = field(default_factory=list)          # report citations (document mode)


def _issue(c: Claim) -> Issue:
    return Issue(category="HALLUCINATION", severity="major", description=f"{c.kind} {c.text}: {c.why}"[:500],
                 location=f"{c.doc}:{c.line}", evidence=(c.sentence or c.text)[:500],
                 fix_hint="state only what the facts show, or delete the sentence")


def current_claims(docs: Docs, inp: DocInput) -> list[Claim]:
    checker = Checker(inp.facts)
    claims = [c for name, md in docs.items() for c in checker.check(md, name)]
    for c in inp.behaviour_bad:                           # still in the document?
        if c.sentence and c.sentence in docs.get(c.doc, ""):
            line = next((i for i, x in enumerate(docs[c.doc].split("\n"), 1) if c.sentence in x), c.line)
            claims.append(c.model_copy(update={"line": line}))
    return claims


def grounding_check(docs: Docs, inp: DocInput) -> list[Issue]:
    issues = [_issue(c) for c in current_claims(docs, inp) if c.verdict == "ungrounded"]
    for e in inp.examples:
        if e.ok is False and e.code.strip() in docs.get(e.doc, ""):
            issues.append(Issue(category="FACTUAL", severity="major",
                                description=f"documented example fails: {e.why}"[:500], location=f"{e.doc}:{e.line}",
                                evidence=e.code[:500], fix_hint="fix or remove the example"))
    return issues


class _Missing(BaseModel):
    missing: list[str] = Field(default_factory=list, max_length=8)


class CompletenessCritic:
    name = "completeness"
    kind: Literal["programmatic", "llm"] = "llm"

    async def review(self, output: Docs, task_input: DocInput, ctx: RefineContext) -> Critique:
        issues = []
        for doc, heads in task_input.required.items():           # cheap part first: required headings
            have = {h.strip().lower() for h in re.findall(r"^#+\s+(.+)$", output.get(doc, ""), re.M)}
            for h in heads:
                if h.lower() not in have:
                    issues.append(Issue(category="OMISSION", severity="minor", description=f"{doc}: no '{h}' section",
                                        location=doc))
        if ctx.has_llm and task_input.deliverables:
            found = {d: re.findall(r"^#+\s+(.+)$", md, re.M)[:40] for d, md in output.items()}
            prompt = ("Required deliverables: " + "; ".join(task_input.deliverables[:10]) + "\nHeadings of the "
                      f"documents: {found}\nList the required deliverables (copy their names) that no document "
                      "covers. An empty list if all are covered.")
            try:
                ans = await ctx.generate("reasoner", [Message(role="system", content="You review documentation. "
                                                              + UNTRUSTED), Message(role="user", content=prompt)],
                                         schema=_Missing, max_tokens=300)
                known = {d.lower(): d for d in task_input.deliverables}
                for m in ans.missing:
                    if m.lower().strip() in known:
                        issues.append(Issue(category="OMISSION", severity="minor",
                                            description=f"deliverable not covered: {known[m.lower().strip()]}"))
            except Exception as exc:
                log.info("completeness critic skipped", error=type(exc).__name__)
        score = max(0.0, 1.0 - 0.05 * len(issues))
        return Critique(score=score, issues=issues, critic=self.name)


class _Rewrite(BaseModel):
    sentence: str = Field(default="", max_length=600)
    delete: bool = False


class SentenceReviser:
    name = "sentence-rewrite"

    async def revise(self, output: Docs, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: Any = None, strategy: str = "targeted") -> Revision:
        docs = dict(output)
        notes: list[str] = []
        applied = 0
        inp: DocInput = task_input
        for issue in critique.issues:
            if issue.category not in ("HALLUCINATION", "FACTUAL") or not issue.location or not issue.evidence:
                continue
            doc = issue.location.split(":")[0]
            target = issue.evidence
            if target not in docs.get(doc, ""):
                continue
            new = ""
            if ctx.has_llm and strategy != "full" and issue.category == "HALLUCINATION" and len(target) > 30:
                new = await self._rewrite(ctx, target, issue.description, inp.facts)
            if new and new != target:
                docs[doc] = docs[doc].replace(target, new, 1)
                notes.append(f"rewrote in {doc}: {target[:80]!r}")
            else:
                docs[doc] = _delete(docs[doc], target)
                notes.append(f"deleted from {doc}: {target[:80]!r}")
            applied += 1
        return Revision(output=docs, notes=notes, applied=applied)

    @staticmethod
    async def _rewrite(ctx: RefineContext, sentence: str, why: str, facts: Facts) -> str:
        known = (f"Dependencies: {', '.join(sorted(facts.dependencies)[:30]) or 'none'}. Ports: "
                 f"{', '.join(map(str, facts.ports)) or 'none'}. Endpoints: "
                 f"{', '.join(f'{r.method} {r.path}' for r in facts.routes[:30]) or 'none'}. Environment variables: "
                 f"{', '.join(list(facts.env)[:30]) or 'none'}.")
        prompt = (f"This documentation sentence is wrong: {sentence}\nWhy: {why}\nWhat the code has: {known}\n"
                  "Rewrite the sentence so it states only what the code has, or set delete=true if nothing true "
                  "remains.")
        try:
            ans = await ctx.generate("reasoner", [Message(role="system", content="You fix documentation. " + UNTRUSTED),
                                                  Message(role="user", content=prompt)], schema=_Rewrite,
                                     max_tokens=300)
        except Exception as exc:
            log.info("rewrite skipped", error=type(exc).__name__)
            return ""
        return "" if ans.delete else " ".join(ans.sentence.split())


def _delete(md: str, sentence: str) -> str:
    out = []
    for line in md.split("\n"):
        if sentence in line:
            line = line.replace(sentence, "", 1)
            if not re.sub(r"[\s|*>\-`#.]", "", line):
                continue
            line = re.sub(r"\s{2,}", " ", line).rstrip()
        out.append(line)
    return "\n".join(out)


@dataclass
class LoopResult:
    docs: Docs
    accuracy: Accuracy
    rounds: int
    stop_reason: str
    scores: list[float]
    notes: list[str]
    tokens: int


async def refine(docs: Docs, inp: DocInput, llm: Any, *, max_rounds: int, check_cancelled: Any = None) -> LoopResult:
    refiner = Refiner(critics=[ProgrammaticCritic(grounding_check, name="grounding", covers={"HALLUCINATION"}),
                               CompletenessCritic()],
                      reviser=SentenceReviser(), classifier=IssueClassifier(use_llm=False),
                      stop=any_of(Threshold(0.999), MaxIters(max_rounds), Plateau(0.01, 1)),
                      name="docgen", producer_name="docgen generators", hard_max_iters=max_rounds)
    ctx = RefineContext(llm=llm, check_cancelled=check_cancelled)
    initial = [c for c in current_claims(docs, inp) if c.verdict == "ungrounded"]
    res = await refiner.run(inp, ctx, output=docs)
    final: Docs = dict(res.final_output)
    notes = [n for a in res.attempts for n in a.revision_notes]
    claims = current_claims(final, inp)
    bad = [c for c in claims if c.verdict == "ungrounded"]
    removed: list[Claim] = []
    for name in final:                                     # the final gate
        doc_bad = [c for c in bad if c.doc == name]
        if doc_bad:
            final[name], gone = remove_sentences(final[name], doc_bad)
            removed += gone
    still = {(c.doc, c.kind, c.text) for c in bad}
    for c in initial:                                     # fixed inside the loop: still reported (honest pct)
        if (c.doc, c.kind, c.text) not in still:
            removed.append(c.model_copy(update={"why": f"{c.why} (removed by the refine loop)"}))
    kept = [c for c in claims if c not in removed] + inp.extra
    acc = summarize([c for c in kept if c.verdict != "ungrounded"] + [c for c in kept if c.verdict == "ungrounded"
                                                                      and c not in removed], removed)
    acc.examples = inp.examples
    return LoopResult(docs=final, accuracy=acc, rounds=res.iterations, stop_reason=res.stop_reason,
                      scores=[a.score for a in res.attempts], notes=notes, tokens=res.usage.tokens)

"""The verification pipeline (Sprint 6 §4): claim → atoms → L1 → L2 → L3 → L4 → decision table → roll-up.

Layers run cheapest first and stop early: a claim whose quotes fail L1 never reaches a model; L3/L4 run only for
parts the cited quotes support (they can only turn VERIFIED into CONFLICTING, or add agreeing sources). ``layers``
switches layers off for the ablation (6.10): ``{"l1"}`` → ``{"l1","l2"}`` → all four.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from hmap.agents.verify import aggregate, claims, compare, entail, independent, mechanical
from hmap.agents.verify.entail import Usage
from hmap.agents.verify.independent import PageLookup
from hmap.agents.verify.mechanical import PageLoader
from hmap.agents.verify.model import LAYERS, AtomCheck, ClaimCheck, Passage, Quote, VerificationTrace, now
from hmap.core.contracts import ClaimVerdict, ResearchReport, VerificationReport
from hmap.core.llm.base import LLMClient


def _noop() -> None:
    return None


@dataclass
class VerifyDeps:
    llm: LLMClient | None
    load_page: PageLoader
    providers: Sequence[object] = ()
    lookup: PageLookup | None = None
    layers: frozenset[str] = frozenset(LAYERS)
    swap: bool = True
    number_guard: bool = True
    concurrency: int = 4
    check_cancelled: Callable[[], None] = _noop
    progress: Callable[[int, int], Awaitable[None]] | None = None
    usage: Usage = field(default_factory=Usage)


def quotes_of(report: ResearchReport) -> dict[str, Quote]:
    return {e.id: Quote(id=e.id, url=e.url, quote=e.quote, content_sha256=e.content_sha256,
                        page_artifact=e.page_artifact) for e in report.evidence}


async def check_claim(claim_id: str, text: str, evidence_ids: Sequence[str], evidence: dict[str, Quote],
                      deps: VerifyDeps, *, counter: Sequence[Passage] = ()) -> ClaimCheck:
    deps.check_cancelled()
    out = ClaimCheck(claim_id=claim_id, text=text, evidence_ids=list(evidence_ids))
    l1 = await mechanical.check_claim(evidence_ids, evidence, deps.load_page)
    cited = [evidence[r.evidence_id] for r in l1 if r.ok]
    cited_urls = [q.url for q in cited]
    for atom in claims.atomize(claim_id, text):
        a = AtomCheck(atom_id=atom.atom_id, text=atom.text, check_worthy=atom.check_worthy, l1=l1)
        out.atoms.append(a)
        if not atom.check_worthy:
            a.row, a.verdict, a.explanation = "skip", "VERIFIED", "not a checkable statement"
            continue
        if not mechanical.passed(l1) or "l2" not in deps.layers:
            aggregate.decide(a, deps.layers)
            continue
        deps.check_cancelled()
        a.l2 = await entail.judge(deps.llm, a.text, [(q.url, q.quote) for q in cited], swap=deps.swap,
                                  use_guard=deps.number_guard, usage=deps.usage)
        if a.l2.label == "supports" and not a.l2.unsure and "l4" in deps.layers:
            others: list[Passage] = list(counter)
            if "l3" in deps.layers and deps.providers and deps.lookup is not None:
                found = await independent.retrieve(a.text, providers=deps.providers, lookup=deps.lookup,
                                                   exclude_urls=set(cited_urls), llm=deps.llm, usage=deps.usage)
                a.l3_queries, a.l3_passages = found.queries, len(found.passages)
                others += found.passages
            if others:
                deps.check_cancelled()
                a.l4 = await compare.compare(a.text, others, llm=deps.llm, usage=deps.usage)
                a.independent_hosts = compare.independent_sites(a.l4, cited_urls)
        aggregate.decide(a, deps.layers)
    return aggregate.roll_up(out)


async def verify_report(report: ResearchReport, deps: VerifyDeps, trace: VerificationTrace) -> VerificationReport:
    """Check every claim of ``report``; fills ``trace`` and returns the ``VerificationReport``."""
    started = time.monotonic()
    evidence = quotes_of(report)
    trace.layers = sorted(deps.layers)
    sem = asyncio.Semaphore(max(1, deps.concurrency))
    done = 0

    async def one(i: int) -> ClaimCheck:
        nonlocal done
        c = report.claims[i]
        async with sem:
            result = await check_claim(c.id, c.text, c.evidence_ids, evidence, deps)
        done += 1
        if deps.progress is not None:
            await deps.progress(done, len(report.claims))
        return result

    trace.claims = list(await asyncio.gather(*(one(i) for i in range(len(report.claims)))))
    trace.follow_up_questions = aggregate.follow_up_questions(trace.claims)
    trace.model_calls, trace.tokens = deps.usage.calls, deps.usage.tokens
    if deps.usage.errors:
        trace.notes.append(f"{len(deps.usage.errors)} model call(s) failed; the rules decided those checks")
    trace.status, trace.finished_at = "done", now()
    trace.seconds = round(time.monotonic() - started, 3)
    return build_report(trace)


def build_report(trace: VerificationTrace) -> VerificationReport:
    return VerificationReport(
        task_id=trace.task_id, research_report_ref=trace.research_report,
        claim_verdicts=[ClaimVerdict(claim_id=c.claim_id, verdict=c.verdict, confidence=round(c.confidence, 3),
                                     supporting=c.supporting, contradicting=c.contradicting,
                                     explanation=c.explanation[:1500]) for c in trace.claims],
        follow_up_questions=trace.follow_up_questions)

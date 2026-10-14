"""The research loop (Sprint 5 §4): plan -> rounds of search / fetch / index / select / extract / track -> stop ->
synthesise. Pure orchestration over injected parts, so tests can run it with a fake model, mock providers and the
memory index; the agent (``agent.py``) wires the real ones.

Round r searches only the sub-questions that are not covered yet, each with its r-th planned query, in every
provider; new pages are fetched (within ``budget.max_sources``), cleaned and indexed; each open sub-question takes
its best chunks (hybrid retrieval + source scoring); the evidence extractor quotes them (checked verbatim); the
coverage tracker and Member 4's stop policies decide whether another round is worth it. Only the planner's
sub-questions ever produce queries: page text never does (prompt-injection rule, plan D12).
"""

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from hmap.agents.refine.core import CountingLLM, Usage
from hmap.agents.refine.stop import LoopState
from hmap.agents.research import evidence as ev
from hmap.agents.research import planner, select, stop, synthesize
from hmap.agents.research.fetch import Fetcher
from hmap.agents.research.index import HybridIndex
from hmap.agents.research.model import EvidenceDraft, Hit, Page, ResearchTrace, RoundTrace, Scored, now
from hmap.agents.research.providers import CachedProvider, SearchError
from hmap.core.contracts import ResearchBrief, ResearchReport
from hmap.core.contracts.domain import Claim, Evidence, Source, SubQuestion
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger
from hmap.obs import span

log = get_logger("hmap.research.pipeline")

ProgressFn = Callable[[ResearchTrace, list[SubQuestion]], Awaitable[None]]


@dataclass
class ResearchDeps:
    llm: LLMClient | None
    providers: Sequence[CachedProvider]
    fetcher: Fetcher
    index: HybridIndex
    project_id: str
    mode: str = "cached"
    progress: ProgressFn | None = None
    check_cancelled: Callable[[], None] = lambda: None
    hits_per_query: int = 4
    chunks_per_sub: int = 4
    candidates_per_sub: int = 8


@dataclass
class ResearchOutcome:
    report: ResearchReport
    trace: ResearchTrace
    pages: dict[str, Page]                      # url -> page cited by the evidence (stored as research-page)
    claim_sub: dict[str, str] = field(default_factory=dict)
    evidence: list[EvidenceDraft] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    best: dict[str, Scored] = field(default_factory=dict)
    prev_refs: dict[str, Any] = field(default_factory=dict)


def _previous_evidence(prev: ResearchReport | None) -> list[EvidenceDraft]:
    if prev is None:
        return []
    from urllib.parse import urlsplit

    return [EvidenceDraft(id=e.id, sub_question=e.sub_question or "", url=e.url, quote=e.quote, char_start=0,
                          char_end=len(e.quote), content_sha256=e.content_sha256, retrieved_at=e.retrieved_at,
                          host=(urlsplit(e.url).hostname or "").lower()) for e in prev.evidence]


async def run_research(brief: ResearchBrief, deps: ResearchDeps, *, previous: ResearchReport | None = None,
                       trace: ResearchTrace | None = None) -> ResearchOutcome:
    usage = Usage()
    llm: LLMClient | None = CountingLLM(deps.llm, usage) if deps.llm is not None else None
    trace = trace or ResearchTrace(task_id=brief.task_id, project_id=deps.project_id, mode=deps.mode,
                                   providers=[p.name for p in deps.providers])
    started = time.perf_counter()

    # ---- plan (a follow-up keeps the earlier questions, sub-questions and evidence; it plans only the gaps)
    subs, trace.planner = await planner.plan(brief, llm)
    evidence = _previous_evidence(previous)
    questions = list(brief.questions)
    if previous is not None:
        offset = len(previous.questions)
        subs = [*previous.sub_questions,
                *[s.model_copy(update={"id": f"S{s.question + offset + 1}.{s.id.split('.')[1]}",
                                       "question": s.question + offset}) for s in subs]]
        questions = [*previous.questions, *brief.questions]
        trace.follow_up_of = brief.follow_up_of
    deps.check_cancelled()

    policy = stop.research_policy(brief.budget)
    state = LoopState()
    exhausted: set[str] = set()
    pages: dict[str, Page] = {}
    fetched_urls: set[str] = set()
    used_vectors: dict[str, list[list[float]]] = {}
    used_text: dict[str, list[str]] = {}
    known = {(e.url, e.char_start) for e in evidence}
    best_scores: dict[str, Scored] = {}
    reason: str | None = None
    subs = stop.update(subs, evidence, 0, exhausted)

    for r in range(stop.HARD_MAX_ROUNDS):
        rt = RoundTrace(index=r + 1)
        mark_tokens, mark_time = usage.tokens, time.perf_counter()
        open_subs = [s for s in subs if s.status not in ("covered", "exhausted")]
        with span("research.round", attrs={"hmap.round": r + 1, "hmap.open_sub_questions": len(open_subs)}):
            # ---- search
            hits_for: dict[str, list[Hit]] = {}
            for s in open_subs:
                if r >= len(s.queries):
                    exhausted.add(s.id)
                    continue
                query = s.queries[r]
                found: list[Hit] = []
                for p in deps.providers:
                    deps.check_cancelled()
                    try:
                        with span(f"research.search {p.name}", kind="client", attrs={"hmap.provider": p.name}) as sp:
                            hits = await p.search(query, deps.hits_per_query)
                            sp.set("hmap.hits", len(hits))
                    except SearchError as exc:
                        rt.fetch_failures[f"search:{p.name}"] = rt.fetch_failures.get(f"search:{p.name}", 0) + 1
                        log.info("research search failed", provider=p.name, error=str(exc)[:80])
                        hits = []
                    rt.queries.append({"sub_question": s.id, "provider": p.name, "query": query, "hits": len(hits)})
                    found += hits
                hits_for[s.id] = found
                rt.hits += len(found)

            # ---- fetch + index (round-robin over providers' ranks, within the source budget)
            pending: list[Hit] = []
            for hits in hits_for.values():
                for h in sorted(hits, key=lambda h: h.rank):
                    if h.url not in fetched_urls and all(h.url != x.url for x in pending):
                        pending.append(h)
            for h in pending:
                if len(fetched_urls) >= brief.budget.max_sources:
                    rt.fetch_failures["source_budget"] = rt.fetch_failures.get("source_budget", 0) + 1
                    continue
                deps.check_cancelled()
                fetched_urls.add(h.url)
                result = await deps.fetcher.fetch(h)
                if result.page is None:
                    rt.fetch_failures[result.reason] = rt.fetch_failures.get(result.reason, 0) + 1
                    continue
                page = result.page
                pages[page.url] = page
                rt.fetched += 1
                await deps.index.add(deps.project_id, page)

            # ---- select per open sub-question
            run_urls = set(pages)
            cands: list[ev.Candidate] = []
            for s in open_subs:
                if s.id in exhausted or not run_urls:
                    continue
                query = f"{s.text} {s.queries[min(r, len(s.queries) - 1)]}"
                retrieved = await deps.index.search(deps.project_id, query, k=deps.candidates_per_sub, urls=run_urls)
                chosen = select.select(retrieved, question=s.text, k=deps.chunks_per_sub,
                                       published={u: p.published for u, p in pages.items()},
                                       already=used_vectors.get(s.id, []), seen_text=used_text.get(s.id, []),
                                       used_urls=[e.url for e in evidence if e.sub_question == s.id])
                for sc in chosen:
                    vec = next((x.vector for x in retrieved if x.chunk.id == sc.chunk.id and x.vector), None)
                    used_vectors.setdefault(s.id, []).append(vec or [])
                    used_text.setdefault(s.id, []).append(sc.chunk.text)
                    cands.append(ev.Candidate(cid=f"C{len(cands) + 1}", sub=s, scored=sc, page=pages[sc.chunk.url]))
                    rt.selected.append({"sub_question": s.id, "url": sc.chunk.url, "chunk": sc.chunk.id,
                                        "score": sc.score, "breakdown": sc.breakdown})
                    prev_best = best_scores.get(sc.chunk.url)
                    if prev_best is None or sc.score > prev_best.score:
                        best_scores[sc.chunk.url] = sc

            # ---- evidence
            deps.check_cancelled()
            got = await ev.extract(cands, llm, first_id=len(evidence) + 1, known=known) if cands else ev.Extraction()
            evidence += got.evidence
            rt.triaged, rt.relevant = got.triaged, got.relevant
            rt.quotes_proposed, rt.quotes_dropped = got.proposed, got.dropped
            rt.new_evidence = len(got.evidence)
            rt.novelty = round(len(got.evidence) / len(evidence), 3) if evidence else 0.0

            # ---- coverage + stop
            subs = stop.update(subs, evidence, r + 1, exhausted)
            rt.coverage = {s.id: s.coverage for s in subs}
            rt.tokens, rt.seconds = usage.tokens - mark_tokens, round(time.perf_counter() - mark_time, 3)
            trace.rounds.append(rt)
            nothing_left = all(s.status in ("covered", "exhausted") or r + 1 >= len(s.queries) for s in subs)
            score = sum(s.coverage for s in subs) / len(subs) if subs else 0.0
            state = replace(state.record(score, tokens=usage.tokens, seconds=usage.seconds),
                            extra={"novelty": rt.novelty, "nothing_left": nothing_left})
            trace.tokens, trace.model_calls = usage.tokens, usage.calls
            trace.seconds = round(time.perf_counter() - started, 3)
            if deps.progress is not None:
                await deps.progress(trace, subs)
            raw = policy.check(state)
            if raw is not None:
                reason = stop.research_reason(raw)
                break
    else:
        reason = "max_rounds"
    if not evidence:
        reason = "no_sources"

    # ---- synthesise
    deps.check_cancelled()
    claims, claim_sub, dropped, trace.synthesis = await synthesize.synthesize(subs, evidence, llm)
    trace.claims_dropped = dropped
    prev_refs = {e.url: e.page_artifact for e in previous.evidence if e.page_artifact} if previous else {}
    report = build_report(brief.task_id, questions, subs, claims, claim_sub, evidence, pages, best_scores,
                          reason or "max_rounds", prev_refs)
    trace.status, trace.stop_reason = "stopped", report.stop_reason
    if deps.index.embed_error:
        trace.notes.append(f"embeddings unavailable ({deps.index.embed_error}): keyword search only")
    trace.tokens, trace.model_calls = usage.tokens, usage.calls
    trace.seconds, trace.finished_at = round(time.perf_counter() - started, 3), now()
    cited = {e.url for e in evidence}
    return ResearchOutcome(report=report, trace=trace, pages={u: p for u, p in pages.items() if u in cited},
                           claim_sub=claim_sub, evidence=evidence, questions=questions, best=best_scores,
                           prev_refs=prev_refs)


def build_report(task_id: str, questions: Sequence[str], subs: Sequence[SubQuestion], claims: Sequence[Claim],
                 claim_sub: dict[str, str], evidence: Sequence[EvidenceDraft], pages: dict[str, Page],
                 best: dict[str, Scored], stop_reason: str, page_refs: dict[str, Any] | None = None) -> ResearchReport:
    page_refs = page_refs or {}
    used = list(dict.fromkeys(e.url for e in evidence))
    sources = []
    for url in used:
        p = pages.get(url)
        sc = best.get(url)
        sources.append(Source(url=url, title=(p.title if p else "") or url, score=sc.score if sc else None,
                              score_breakdown=sc.breakdown if sc else {}, provider=p.provider if p else None,
                              kind=p.kind if p else None, retrieved_at=p.retrieved_at if p else None,
                              content_sha256=p.content_sha256 if p else None, page_artifact=page_refs.get(url)))
    ev_out = [Evidence(id=e.id, url=e.url, quote=e.quote, content_sha256=e.content_sha256, retrieved_at=e.retrieved_at,
                       sub_question=e.sub_question, page_artifact=page_refs.get(e.url)) for e in evidence]
    md = synthesize.summary_markdown(questions, subs, claims, claim_sub, evidence, stop_reason)
    return ResearchReport(task_id=task_id, questions=list(questions), claims=list(claims), evidence=ev_out,
                          sources=sources, coverage={s.id: s.coverage for s in subs}, stop_reason=stop_reason,
                          summary_markdown=md, sub_questions=list(subs))

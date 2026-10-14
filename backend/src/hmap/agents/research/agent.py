"""``ResearchAgent`` (Sprint 5 item 5.10): the real ``research.run``.

Input (built from the ``TaskAssign``, plan D1 — the Manager already passes Member 3's seeds):

- questions: ``inputs.research_questions`` (else the task objective), at most 5;
- scope: the project's latest ``requirement-set`` (a few requirement texts), else the objective;
- constraints: the step's acceptance criteria; budget: ``inputs.budget`` over ``ResearchBudget`` defaults;
- follow-up (Member 6, plan D15): ``inputs.follow_up_of`` = an earlier ``research-report`` ref; the questions are
  the gaps; earlier evidence is kept.

Output: ``research-report`` (first), ``research-trace``, ``research-brief`` and one ``research-page`` per cited page
(the cleaned text quotes were checked against; content-addressed, so the same page is stored once per project).
Progress per round (``task.progress`` with the trace ref). Cancellation is checked between steps. Idempotent: a
redelivered task with the same brief returns the stored result (in-process LRU, like ``RefineAgent``). With
``task.refine`` the report goes through Member 4's refinement (``synthesize.refine_setup``).
"""

import json
from collections import OrderedDict
from typing import Any, ClassVar

from hmap.agents.research import pipeline
from hmap.agents.research.clean import CleanError, page_from_text
from hmap.agents.research.fetch import Fetcher
from hmap.agents.research.index import HybridIndex, backend_for
from hmap.agents.research.model import BRIEF_TYPE, PAGE_TYPE, REPORT_TYPE, TRACE_TYPE, Page, ResearchTrace
from hmap.agents.research.providers import get_providers, page_store
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, ResearchBrief, ResearchReport, TaskAssign, TaskResult
from hmap.core.contracts.capabilities import RESEARCH_RUN
from hmap.core.contracts.domain import ResearchBudget, SubQuestion
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.tracing import get_logger

log = get_logger("hmap.research.agent")
MAX_QUESTIONS = 5
_DONE: "OrderedDict[str, list[ArtifactRef]]" = OrderedDict()
_DONE_MAX = 64


def _digest(*parts: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


async def _latest(ctx: AgentContext, artifact_type: str) -> ArtifactRef | None:
    refs = [r for r in await ctx.artifacts.list(ctx.project_id) if r.artifact_type == artifact_type]
    return max(refs, key=lambda r: (r.created_at, r.version), default=None)


async def build_brief(task: TaskAssign, ctx: AgentContext) -> ResearchBrief:
    raw = task.inputs.get("research_questions") or []
    questions = [str(q).strip() for q in raw if str(q).strip()][:MAX_QUESTIONS] or [task.objective.strip()]
    scope = task.objective.strip()
    rs_ref = await _latest(ctx, "requirement-set")
    if rs_ref is not None:
        try:
            rs = json.loads(await ctx.artifacts.get(rs_ref, project_id=ctx.project_id))
            reqs = [str(r.get("text", "")) for r in rs.get("requirements", [])[:6]]
            scope = (scope + " | Project requirements: " + "; ".join(reqs))[:900]
        except Exception:  # scope is context only
            pass
    budget = ResearchBudget.model_validate(task.inputs.get("budget") or {})
    follow = task.inputs.get("follow_up_of")
    return ResearchBrief(task_id=task.task_id, questions=questions, scope=scope,
                         constraints=list(task.acceptance_criteria)[:8], budget=budget,
                         follow_up_of=ArtifactRef.model_validate(follow) if isinstance(follow, dict) else None)


async def project_pages(ctx: AgentContext) -> list[Page]:
    """The project's own uploaded documents as local pages (``project://<doc id>``), from Member 2's document model."""
    ref = await _latest(ctx, "document-model")
    if ref is None:
        return []
    try:
        dm = json.loads(await ctx.artifacts.get(ref, project_id=ctx.project_id))
    except Exception:
        return []
    out: list[Page] = []
    for doc in dm.get("documents", []):
        text = str(doc.get("text") or "\n".join(b.get("text", "") for b in doc.get("blocks", [])))
        try:
            out.append(page_from_text(text, url=f"project://{doc.get('doc_id')}", title=str(doc.get("name", "")),
                                      kind="local", provider="project", media_type="text/plain"))
        except CleanError:
            continue
    return out


async def failure_injection(task: TaskAssign, ctx: AgentContext) -> None:
    """The platform's test / demo hooks, honoured like the stub did (chaos tests, the mid-eval failure injection):
    ``inputs.stub_fail`` (+ ``stub_fail_times``) fails the first attempts with that error code; ``inputs.stub_delay_s``
    keeps the step busy (cancellable) so its agent can be killed mid-task. Only when a task asks for it explicitly."""
    import asyncio

    from hmap.agents.stubs.agents import MAX_DELAY_S, maybe_fail

    maybe_fail(task)
    delay = min(max(float(task.inputs.get("stub_delay_s") or 0), 0.0), MAX_DELAY_S)
    loop = asyncio.get_running_loop()
    end = loop.time() + delay
    while (left := end - loop.time()) > 0:
        ctx.check_cancelled()
        await asyncio.sleep(min(0.05, left))


class ResearchAgent(BaseAgent):
    name = "research"
    capabilities: ClassVar[tuple[str, ...]] = (RESEARCH_RUN,)
    max_slots: ClassVar[int] = 1
    version: ClassVar[str] = "1.0"

    def __init__(self, settings: Settings | None = None, **deps: Any) -> None:
        self.settings = settings
        self.deps = deps                 # tests: providers=..., fetcher=..., client=...

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await failure_injection(task, ctx)
        settings = self.settings or Settings.from_env()
        mode = str(task.inputs.get("research_mode") or settings.research_mode)
        mode = mode if mode in ("online", "cached", "local") else settings.research_mode
        brief = await build_brief(task, ctx)
        key = _digest(task.task_id, brief.model_dump(mode="json", exclude={"task_id"}), mode)
        if key in _DONE:
            _DONE.move_to_end(key)
            return ctx.result(_DONE[key], summary="research already done for this brief (redelivered)")
        brief_ref = await ctx.put_json(brief, artifact_type=BRIEF_TYPE, artifact_id=f"rb-{task.task_id}")
        previous: ResearchReport | None = None
        if brief.follow_up_of is not None:
            previous = await ctx.get_json(brief.follow_up_of, ResearchReport)

        store = self.deps.get("store") or page_store(settings)
        local_pages = await project_pages(ctx)
        providers = self.deps.get("providers") or get_providers(mode=mode, settings=settings, store=store,
                                                                project_pages=local_pages,
                                                                client=self.deps.get("client"))
        fetcher = self.deps.get("fetcher") or Fetcher(store=store, mode=mode, client=self.deps.get("client"),
                                                      rate_per_host=settings.research_rate_per_host,
                                                      max_bytes=int(settings.research_max_fetch_mb * 1024 * 1024),
                                                      extra_pages={p.url: p for p in local_pages})
        index = HybridIndex(embed=ctx.llm.embed, backend=self.deps.get("backend") or backend_for(ctx.context))
        trace_id = f"rt-{task.task_id}"
        last_trace: list[ArtifactRef] = []

        async def progress(trace: ResearchTrace, subs: list[SubQuestion]) -> None:
            ref = await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=trace_id)
            last_trace[:] = [ref]
            done = len(trace.rounds)
            covered = sum(1 for s in subs if s.status == "covered")
            pct = min(85, 10 + int(75 * done / max(1, brief.budget.max_rounds)))
            await ctx.progress(pct, f"round {done}: {sum(r.fetched for r in trace.rounds)} sources read, "
                                    f"{covered}/{len(subs)} sub-questions covered", artifact_refs=[ref])

        trace = ResearchTrace(task_id=task.task_id, project_id=ctx.project_id, mode=mode,
                              providers=[p.name for p in providers])
        deps = pipeline.ResearchDeps(llm=ctx.llm, providers=providers, fetcher=fetcher, index=index,
                                     project_id=ctx.project_id, mode=mode, progress=progress,
                                     check_cancelled=ctx.check_cancelled)
        try:
            outcome = await pipeline.run_research(brief, deps, previous=previous, trace=trace)
        finally:
            if "fetcher" not in self.deps:
                await fetcher.aclose()

        # cited pages, content-addressed (the same text is stored once per project)
        page_refs: dict[str, ArtifactRef] = dict(outcome.prev_refs)
        for url, page in outcome.pages.items():
            pid = f"rp-{page.content_sha256[:32]}"
            ref = await ctx.artifacts.latest(pid, project_id=ctx.project_id)
            if ref is None:
                ref = await ctx.put_json(page, artifact_type=PAGE_TYPE, artifact_id=pid)
            page_refs[url] = ref
        report = pipeline.build_report(task.task_id, outcome.questions, outcome.report.sub_questions,
                                       outcome.report.claims, outcome.claim_sub, outcome.evidence,
                                       {**outcome.pages}, outcome.best, outcome.report.stop_reason, page_refs)
        outcome.trace.pages = list({r.artifact_id: r for r in page_refs.values()}.values())
        report_ref = await ctx.put_json(report, artifact_type=REPORT_TYPE)
        trace_ref = await ctx.put_json(outcome.trace, artifact_type=TRACE_TYPE, artifact_id=trace_id)
        refs = [report_ref, trace_ref, brief_ref, *outcome.trace.pages]
        covered = sum(1 for s in report.sub_questions if s.status == "covered")
        summary = (f"{len(report.claims)} cited claims from {len(report.sources)} sources; {covered}/"
                   f"{len(report.sub_questions)} sub-questions covered; stopped: "
                   f"{report.stop_reason.replace('_', ' ')}")
        result = ctx.result(refs, summary=summary)
        if task.refine and report.claims:
            from hmap.agents.refine.integration import refine_result
            from hmap.agents.research.synthesize import refine_setup

            result = await refine_result(task, result, ctx, refine_setup(report, outcome.claim_sub,  # type: ignore[arg-type]
                                                                         outcome.evidence))
        _DONE[key] = list(result.artifact_refs)
        while len(_DONE) > _DONE_MAX:
            _DONE.popitem(last=False)
        log.info("research done", task_id=task.task_id, claims=len(report.claims), evidence=len(report.evidence),
                 stop=report.stop_reason, rounds=len(outcome.trace.rounds))
        return result

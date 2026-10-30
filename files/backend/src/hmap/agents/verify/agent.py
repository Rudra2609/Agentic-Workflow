"""``VerifyAgent`` (Sprint 6 item 6.7): the real ``verify.claims``.

Input (from the ``TaskAssign``):

- the report: ``inputs.research_report`` (a ``research-report`` ref, set by the follow-up hook / API), else the
  newest ``research-report`` among the task's ``artifact_refs`` (the Manager hands the verify step its research
  step's results). **No report** (e.g. a document project's *test* step, or a stub upstream) → an empty
  ``VerificationReport`` saying there was nothing to verify; the step succeeds;
- ``inputs.verify_round`` (0 = first check), ``inputs.follow_up_of_verification`` (the report being re-checked);
- ``inputs.layers`` (optional subset of l1..l4), ``inputs.research_mode`` (else ``HMAP_RESEARCH_MODE``).

Output: ``verification-report`` (``vr-<task_id>``, first) + ``verification-trace`` (``vt-<task_id>``). Idempotent:
a redelivered task whose report was already checked returns the stored artifacts (looked up in the artifact store,
so it also holds after an agent restart). Failure-injection inputs (``stub_fail``, ``stub_delay_s``) are honoured
like the stub did (Member 4's and the chaos tests inject failures by capability).
"""

import asyncio
import json
from typing import Any, ClassVar

from hmap.agents.research.corpus import CORPUS_DIR, PageStore
from hmap.agents.research.fetch import Fetcher
from hmap.agents.research.model import Hit, Page
from hmap.agents.research.providers import (
    ArxivProvider,
    CachedProvider,
    DuckDuckGoProvider,
    LocalProvider,
    SearchCache,
    WikipediaProvider,
)
from hmap.agents.research.providers.web import http_client
from hmap.agents.verify import pipeline
from hmap.agents.verify.benchmark import SEARCH_CACHE
from hmap.agents.verify.model import LAYERS, REPORT_TYPE, RESEARCH_REPORT_TYPE, TRACE_TYPE, Quote, VerificationTrace
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, ResearchReport, TaskAssign, TaskResult, VerificationReport
from hmap.core.contracts.capabilities import VERIFY_CLAIMS
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.tracing import get_logger

log = get_logger("hmap.verify.agent")


async def failure_injection(task: TaskAssign, ctx: AgentContext) -> None:
    """The platform's test / demo hooks, only when a task asks for them (as the stub and Member 5's agent do)."""
    from hmap.agents.stubs.agents import MAX_DELAY_S, maybe_fail

    maybe_fail(task)
    delay = min(max(float(task.inputs.get("stub_delay_s") or 0), 0.0), MAX_DELAY_S)
    loop = asyncio.get_running_loop()
    end = loop.time() + delay
    while (left := end - loop.time()) > 0:
        ctx.check_cancelled()
        await asyncio.sleep(min(0.05, left))


def report_ref_of(task: TaskAssign) -> ArtifactRef | None:
    explicit = task.inputs.get("research_report")
    if isinstance(explicit, dict):
        return ArtifactRef.model_validate(explicit)
    refs = [r for r in task.artifact_refs if r.artifact_type == RESEARCH_REPORT_TYPE]
    return max(refs, key=lambda r: (r.created_at, r.version), default=None)


def summary_line(report: VerificationReport) -> str:
    s = report.summary
    n = len(report.claim_verdicts)
    return (f"{n} claims checked: {s['verified']} verified, {s['unsupported']} unsupported, {s['conflicting']} "
            f"conflicting, {s['needs_more']} need more research")


def providers_for(settings: Settings, mode: str, store: PageStore, client: Any) -> list[CachedProvider]:
    """Member 5's providers behind the VERIFIER's own search cache (never the researcher's queries)."""
    cache_dir = settings.verify_cache_dir / "search"
    cache = SearchCache([SEARCH_CACHE, cache_dir], cache_dir)
    out: list[CachedProvider] = []
    for name in settings.research_providers:
        if mode == "local" and name != "local":
            continue
        inner: Any
        if name == "wikipedia":
            inner = WikipediaProvider(client)
        elif name == "arxiv":
            inner = ArxivProvider(client)
        elif name == "ddg":
            inner = DuckDuckGoProvider()
        elif name == "local":
            inner = LocalProvider(store)
        else:
            continue
        out.append(CachedProvider(inner, cache, mode))
    return out


class VerifyAgent(BaseAgent):
    name = "verify"
    capabilities: ClassVar[tuple[str, ...]] = (VERIFY_CLAIMS,)
    max_slots: ClassVar[int] = 1
    version: ClassVar[str] = "1.0"

    def __init__(self, settings: Settings | None = None, **deps: Any) -> None:
        self.settings = settings
        self.deps = deps                 # tests: providers=..., lookup=...

    async def _existing(self, ctx: AgentContext, task_id: str, report_ref: ArtifactRef | None) -> list[ArtifactRef]:
        vr = await ctx.artifacts.latest(f"vr-{task_id}", project_id=ctx.project_id)
        vt = await ctx.artifacts.latest(f"vt-{task_id}", project_id=ctx.project_id)
        if vr is None or vt is None:
            return []
        try:
            trace = VerificationTrace.model_validate_json(await ctx.artifacts.get(vt, project_id=ctx.project_id))
        except Exception:
            return []
        same = (trace.research_report is None and report_ref is None) or (
            trace.research_report is not None and report_ref is not None
            and trace.research_report.artifact_id == report_ref.artifact_id
            and trace.research_report.version == report_ref.version)
        return [vr, vt] if same and trace.status == "done" else []

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await failure_injection(task, ctx)
        settings = self.settings or Settings.from_env()
        report_ref = report_ref_of(task)
        if existing := await self._existing(ctx, task.task_id, report_ref):
            return ctx.result(existing, summary="verification already done for this report (redelivered)")
        follow = task.inputs.get("follow_up_of_verification")
        trace = VerificationTrace(task_id=task.task_id, project_id=ctx.project_id, research_report=report_ref,
                                  round=int(task.inputs.get("verify_round") or 0),
                                  follow_up_of=ArtifactRef.model_validate(follow) if isinstance(follow, dict) else None)
        if report_ref is None:
            trace.status = "done"
            trace.notes.append("no research report among this step's inputs: nothing to verify")
            report = pipeline.build_report(trace)
            refs = [await ctx.put_json(report, artifact_type=REPORT_TYPE, artifact_id=f"vr-{task.task_id}"),
                    await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=f"vt-{task.task_id}")]
            return ctx.result(refs, summary="no research findings to verify")

        research = await ctx.get_json(report_ref, ResearchReport)
        trace.research_task_id = research.task_id
        mode = str(task.inputs.get("research_mode") or settings.research_mode)
        mode = mode if mode in ("online", "cached", "local") else settings.research_mode
        layers = frozenset(str(x) for x in (task.inputs.get("layers") or LAYERS) if str(x) in LAYERS) | {"l1"}
        if not settings.verify_independent:
            layers -= {"l3"}

        pages: dict[str, Page | None] = {}

        async def load_page(q: Quote) -> Page | None:
            if q.page_artifact is None:
                return None
            key = f"{q.page_artifact.artifact_id}@{q.page_artifact.version}"
            if key not in pages:
                try:
                    pages[key] = Page.model_validate_json(await ctx.artifacts.get(q.page_artifact,
                                                                                  project_id=ctx.project_id))
                except Exception:
                    pages[key] = None
            return pages[key]

        store = PageStore([CORPUS_DIR, settings.research_cache_dir / "pages", settings.verify_cache_dir / "pages"],
                          write_dir=settings.verify_cache_dir / "pages")
        client = None if "providers" in self.deps else http_client()
        fetcher = Fetcher(store=store, mode=mode, client=client, rate_per_host=settings.research_rate_per_host,
                          max_bytes=int(settings.research_max_fetch_mb * 1024 * 1024))

        async def lookup(hit: Hit) -> Page | None:
            return (await fetcher.fetch(hit)).page

        async def progress(done: int, total: int) -> None:
            await ctx.progress(10 + int(85 * done / max(1, total)), f"{done}/{total} claims checked")

        deps = pipeline.VerifyDeps(
            llm=ctx.llm, load_page=load_page,
            providers=self.deps.get("providers") or providers_for(settings, mode, store, client),
            lookup=self.deps.get("lookup") or lookup, layers=layers, check_cancelled=ctx.check_cancelled,
            progress=progress)
        await ctx.progress(5, f"checking {len(research.claims)} claims")
        try:
            report = await pipeline.verify_report(research, deps, trace)
        finally:
            await fetcher.aclose()
        report_out = await ctx.put_json(report, artifact_type=REPORT_TYPE, artifact_id=f"vr-{task.task_id}")
        trace_out = await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=f"vt-{task.task_id}")
        log.info("verification done", task_id=task.task_id, round=trace.round, calls=trace.model_calls,
                 **report.summary)
        return ctx.result([report_out, trace_out], summary=summary_line(report),
                          evidence=[json.dumps(report.summary)])

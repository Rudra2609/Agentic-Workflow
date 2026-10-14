"""Research evaluation (Sprint 5 item 5.15, plan D17) + building the offline corpus (item 5.14, D16, D22).

    cd backend
    uv run python -m tests.research.eval.run_eval                       # 10 gold questions, offline (cached + replay)
    uv run python -m tests.research.eval.run_eval --ablation             # + retrieval hybrid / dense / keyword,
                                                                         #   synthesis with / without refinement
    HMAP_LLM_RECORD_MISSING=research uv run python -m tests.research.eval.run_eval --ablation   # record what is missing
    uv run python -m tests.research.eval.run_eval --mode live --local-only   # local qwen3.5:9b, NOT recorded
    uv run python -m tests.research.eval.run_eval --harvest              # ONLINE: search + fetch -> data/
                                                                         #   research_cache
    uv run python -m tests.research.eval.run_eval --curate               # copy permissively licensed pages + search
                                                                         #   results into samples/research/

Offline runs use ONLY the committed corpus (``samples/research/corpus``) and search results
(``samples/research/search_cache``): the local cache is replaced by an empty temporary folder, so the numbers are
reproducible on any laptop. Scores: fact coverage (gold facts found in the claims or cited quotes), citation
validity (every quote verbatim in its page, page hash matches), source quality, rounds, tokens, model calls, time,
stop reasons; retrieval fact-recall@k over the whole corpus.
"""

import argparse
import asyncio
import json
import re
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hmap.agents.research import pipeline, quotes
from hmap.agents.research.corpus import CORPUS_DIR, PageStore
from hmap.agents.research.fetch import Fetcher
from hmap.agents.research.index import HybridIndex, MemoryBackend
from hmap.agents.research.model import Page
from hmap.agents.research.providers import SAMPLE_SEARCH_CACHE, get_providers
from hmap.agents.research.select import authority
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts import ResearchBrief, ResearchReport
from hmap.core.llm.base import LLMClient
from hmap.core.llm.gateway import Gateway

GOLD = REPO_ROOT / "samples" / "research" / "gold"
RESULTS = REPO_ROOT / "samples" / "research" / "eval_results"
LICENSES = {  # host suffix -> licence of the text we keep (committed corpus only)
    "wikipedia.org": "CC BY-SA 4.0 (Wikipedia contributors)",
    "docs.python.org": "PSF Documentation License (Python Software Foundation)",
    "peps.python.org": "Public domain / CC0 (Python Enhancement Proposals)",
    "arxiv.org": "arXiv metadata: CC0 1.0 (title and abstract only)",
    "rfc-editor.org": "IETF Trust Legal Provisions (RFC text may be copied with notice)",
    "datatracker.ietf.org": "IETF Trust Legal Provisions (RFC text may be copied with notice)",
    "docs.pytest.org": "MIT License (pytest documentation)",
    "coverage.readthedocs.io": "Apache License 2.0 (coverage.py documentation)",
    "pytest-cov.readthedocs.io": "MIT License (pytest-cov documentation)",
    "developer.mozilla.org": "CC BY-SA 2.5 (Mozilla Contributors)",
    "fastapi.tiangolo.com": "MIT License (FastAPI documentation)",
    "docs.djangoproject.com": "BSD 3-Clause (Django documentation)",
    "react.dev": "CC BY 4.0 (React documentation)",
    "refactoring.guru": None,          # explicitly NOT redistributable: listed so curation reports it
}


def gold() -> list[dict[str, Any]]:
    return [json.loads(line) for line in (GOLD / "questions.jsonl").read_text().splitlines() if line.strip()]


def licence_for(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    return next((lic for suffix, lic in LICENSES.items() if host == suffix or host.endswith("." + suffix)), None)


def gateway(mode: str, local_only: bool) -> LLMClient:
    settings = Settings.from_env().model_copy(update={"llm_mode": mode})
    gw = Gateway(settings).for_plugin("research")
    return gw.local_only() if local_only else gw


def fact_hits(gold_q: dict[str, Any], report: ResearchReport) -> dict[str, bool]:
    text = "\n".join([c.text for c in report.claims] + [e.quote for e in report.evidence])
    return {f["id"]: any(re.search(p, text, re.IGNORECASE | re.DOTALL) for p in f["any_of"]) for f in gold_q["facts"]}


def citation_validity(report: ResearchReport, pages: dict[str, Page]) -> tuple[int, int]:
    ok = 0
    for e in report.evidence:
        page = pages.get(e.url)
        if page and page.content_sha256 == e.content_sha256 and quotes.locate(e.quote, page.text) is not None:
            ok += 1
    return ok, len(report.evidence)


async def run_one(brief: ResearchBrief, *, llm: LLMClient | None, mode: str, settings: Settings, store: PageStore,
                  ranking: str = "hybrid", refine: bool = False) -> dict[str, Any]:
    providers = get_providers(mode=mode, settings=settings, store=store)
    fetcher = Fetcher(store=store, mode=mode, rate_per_host=settings.research_rate_per_host)
    index = HybridIndex(embed=llm.embed if llm else _no_embed, backend=MemoryBackend(), ranking=ranking)
    deps = pipeline.ResearchDeps(llm=llm, providers=providers, fetcher=fetcher, index=index,
                                 project_id=f"eval-{brief.task_id}", mode=mode)
    started = time.perf_counter()
    try:
        out = await pipeline.run_research(brief, deps)
    finally:
        await fetcher.aclose()
    seconds = time.perf_counter() - started
    report = out.report
    refine_info: dict[str, Any] | None = None
    if refine and report.claims and llm is not None:
        refine_info, report = await _refine(report, out, llm)
    pages = {e.url: p for e in report.evidence if (p := store.get(e.url) or out.pages.get(e.url))}
    return {"report": report, "trace": out.trace, "seconds": seconds, "pages": pages, "refine": refine_info,
            "network_calls": fetcher.network_calls + sum(p.live_calls for p in providers),
            "embed_error": index.embed_error}


async def _refine(report: ResearchReport, out: Any, llm: LLMClient) -> tuple[dict[str, Any], ResearchReport]:
    from hmap.agents.refine import RefineContext, Refiner
    from hmap.agents.research.synthesize import refine_setup

    setup: Any = refine_setup(report, out.claim_sub, out.evidence)
    res = await Refiner(critics=setup.critics, reviser=setup.reviser).run(None, RefineContext(llm=llm), output=report)
    best: ResearchReport = res.final_output
    return ({"base_score": res.base_score, "best_score": res.best_score, "iterations": res.iterations,
             "stop": res.stop_reason, "tokens": res.usage.tokens, "claims_before": len(report.claims),
             "claims_after": len(best.claims)}, best)


async def _no_embed(texts: list[str]) -> list[list[float]]:
    raise RuntimeError("no embedding model")


def score_case(g: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    report: ResearchReport = r["report"]
    hits = fact_hits(g, report)
    ok, total = citation_validity(report, r["pages"])
    auth = [authority(s.url) for s in report.sources]
    return {"facts": f"{sum(hits.values())}/{len(hits)}", "fact_coverage": round(sum(hits.values()) / len(hits), 3),
            "missed_facts": [k for k, v in hits.items() if not v], "claims": len(report.claims),
            "evidence": len(report.evidence), "citation_valid": f"{ok}/{total}", "sources": len(report.sources),
            "source_authority": round(statistics.mean(auth), 3) if auth else None,
            "high_authority_share": round(sum(a >= 0.9 for a in auth) / len(auth), 3) if auth else None,
            "rounds": len(r["trace"].rounds), "stop": report.stop_reason, "tokens": r["trace"].tokens,
            "calls": r["trace"].model_calls, "seconds": round(r["seconds"], 2),
            "quotes_dropped": sum(x.quotes_dropped for x in r["trace"].rounds),
            "quotes_proposed": sum(x.quotes_proposed for x in r["trace"].rounds),
            "planner": r["trace"].planner, "synthesis": r["trace"].synthesis,
            "network_calls": r["network_calls"], "embed_error": r["embed_error"], "refine": r["refine"],
            "sub_questions": [{"id": s.id, "status": s.status, "coverage": s.coverage} for s in report.sub_questions]}


def summarise(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    vals = list(rows.values())
    ok = sum(int(v["citation_valid"].split("/")[0]) for v in vals)
    tot = sum(int(v["citation_valid"].split("/")[1]) for v in vals)
    stops: dict[str, int] = {}
    for v in vals:
        stops[v["stop"]] = stops.get(v["stop"], 0) + 1
    return {"questions": len(vals), "fact_coverage": round(statistics.mean(v["fact_coverage"] for v in vals), 3),
            "citation_validity": f"{ok}/{tot}", "fabricated_quotes_in_report": tot - ok,
            "quotes_dropped_by_check": sum(v["quotes_dropped"] for v in vals),
            "quotes_proposed": sum(v["quotes_proposed"] for v in vals),
            "claims_mean": round(statistics.mean(v["claims"] for v in vals), 2),
            "sources_mean": round(statistics.mean(v["sources"] for v in vals), 2),
            "source_authority_mean": round(statistics.mean(v["source_authority"] for v in vals
                                                           if v["source_authority"] is not None) or 0, 3)
            if any(v["source_authority"] is not None for v in vals) else None,
            "rounds_mean": round(statistics.mean(v["rounds"] for v in vals), 2),
            "tokens_mean": round(statistics.mean(v["tokens"] for v in vals)),
            "calls_mean": round(statistics.mean(v["calls"] for v in vals), 2),
            "seconds_median": round(statistics.median(v["seconds"] for v in vals), 2),
            "stop_reasons": stops, "network_calls": sum(v["network_calls"] for v in vals)}


async def recall_at_k(llm: LLMClient | None, store: PageStore, ks: tuple[int, ...] = (3, 6, 10)) -> dict[str, Any]:
    """Fact recall@k over the whole corpus: for each gold fact, is a chunk that states it among the top k chunks
    retrieved for the question? (hybrid vs dense vs keyword)."""
    pages = store.pages()
    out: dict[str, Any] = {}
    for ranking in ("hybrid", "dense", "keyword"):
        index = HybridIndex(embed=llm.embed if llm else _no_embed, backend=MemoryBackend(), ranking=ranking)
        for p in pages:
            await index.add("recall", p)
        found = {k: 0 for k in ks}
        total = 0
        for g in gold():
            hits = await index.search("recall", g["question"], k=max(ks), pool=40)
            for f in g["facts"]:
                relevant = [n for n, h in enumerate(hits) if any(re.search(p, h.chunk.text, re.IGNORECASE | re.DOTALL)
                                                                 for p in f["any_of"])]
                total += 1
                for k in ks:
                    found[k] += any(n < k for n in relevant)
        out[ranking] = {f"recall@{k}": round(found[k] / total, 3) for k in ks} | {
            "facts": total, "keyword_only": index.keyword_only}
    return out


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="hmap-research-eval-"))
    settings = Settings.from_env().model_copy(update={"research_cache_dir": tmp})   # committed corpus only
    store = PageStore([CORPUS_DIR], write_dir=None)
    llm = None if args.rules else gateway(args.mode, args.local_only)
    mode = "cached"
    conditions = [("hybrid", False)] + ([("dense", False), ("keyword", False), ("hybrid", True)] if args.ablation
                                        else [])
    out: dict[str, Any] = {"llm_mode": "rules" if args.rules else args.mode, "local_only": args.local_only,
                           "research_mode": mode, "corpus_pages": len(store.pages()), "conditions": {}}
    try:
        for ranking, refine in conditions:
            name = ranking + ("+refine" if refine else "")
            rows: dict[str, dict[str, Any]] = {}
            for g in gold():
                if args.only and g["id"] not in args.only:
                    continue
                brief = ResearchBrief(task_id=g["id"], questions=[g["question"]])
                r = await run_one(brief, llm=llm, mode=mode, settings=settings, store=store, ranking=ranking,
                                  refine=refine)
                rows[g["id"]] = score_case(g, r)
                print(f"  [{name}] {g['id']}: facts {rows[g['id']]['facts']}, claims {rows[g['id']]['claims']}, "
                      f"cites valid {rows[g['id']]['citation_valid']}, stop {rows[g['id']]['stop']}, "
                      f"{rows[g['id']]['seconds']} s")
            out["conditions"][name] = {"summary": summarise(rows), "cases": rows}
            print(name, json.dumps(out["conditions"][name]["summary"]))
        if args.ablation:
            out["retrieval"] = await recall_at_k(llm, store)
            print("retrieval", json.dumps(out["retrieval"]))
        if not args.only:
            demo = json.loads((GOLD / "demo_brief.json").read_text())
            brief = ResearchBrief(task_id=demo["id"], questions=demo["questions"])
            r = await run_one(brief, llm=llm, mode=mode, settings=settings, store=store)
            rep: ResearchReport = r["report"]
            ok, total = citation_validity(rep, r["pages"])
            out["demo_brief"] = {"claims": len(rep.claims), "evidence": len(rep.evidence), "sources": len(rep.sources),
                                 "citation_valid": f"{ok}/{total}", "stop": rep.stop_reason,
                                 "covered": sum(s.status == "covered" for s in rep.sub_questions),
                                 "sub_questions": len(rep.sub_questions), "rounds": len(r["trace"].rounds),
                                 "tokens": r["trace"].tokens, "calls": r["trace"].model_calls}
            print("demo brief", json.dumps(out["demo_brief"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


async def harvest(args: argparse.Namespace) -> None:
    """ONLINE: run every gold question + the demo brief with live search and fetch (model: cloud first), so the
    search results and pages land in data/research_cache. Model answers of this run are NOT kept (they are
    re-recorded offline against the curated corpus)."""
    settings = Settings.from_env()
    pages = settings.research_cache_dir / "pages"
    store = PageStore([CORPUS_DIR, pages], write_dir=pages)
    llm = gateway("live", False)
    briefs = [ResearchBrief(task_id=g["id"], questions=[g["question"]], budget={"max_rounds": 3, "max_sources": 25})
              for g in gold()]
    demo = json.loads((GOLD / "demo_brief.json").read_text())
    briefs.append(ResearchBrief(task_id=demo["id"], questions=demo["questions"],
                                budget={"max_rounds": 3, "max_sources": 30}))
    for b in briefs:
        r = await run_one(b, llm=llm, mode="online", settings=settings, store=store)
        print(f"  harvested {b.task_id}: {len(r['pages'])} cited pages, network calls {r['network_calls']}, "
              f"stop {r['report'].stop_reason}")


def curate() -> None:
    """Copy permissively licensed pages (with their licence) and all search results into samples/research/.
    Search results keep url / title / rank (+ the snippet only for permissive sources); page text lives in the
    corpus, so a hit whose page was not kept is simply "not in cache" offline."""
    settings = Settings.from_env()
    src_pages = settings.research_cache_dir / "pages"
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    kept, skipped = 0, {}
    keep_urls: set[str] = set()
    for f in sorted(src_pages.glob("*.json")):
        page = Page.model_validate_json(f.read_text(encoding="utf-8"))
        lic = licence_for(page.url)
        if lic is None:
            host = urlsplit(page.url).hostname or "?"
            skipped[host] = skipped.get(host, 0) + 1
            continue
        page = page.model_copy(update={"license": lic, "from_cache": False})
        (CORPUS_DIR / f.name).write_text(page.model_dump_json(indent=1), encoding="utf-8")
        keep_urls.add(page.url)
        kept += 1
    n_search = 0
    for f in sorted((settings.research_cache_dir / "search").glob("*/*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for h in data.get("hits", []):
            h.pop("content", None)                       # the text lives in the corpus (or nowhere, if not kept)
            if licence_for(h.get("url", "")) is None:
                h["snippet"] = ""
        dest = SAMPLE_SEARCH_CACHE / f.parent.name / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        n_search += 1
    print(f"corpus: {kept} pages kept; not redistributable (left out): {skipped}; search results: {n_search}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("replay", "record", "live"), default="replay")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--rules", action="store_true", help="no model at all (rule fallbacks; keyword search only)")
    ap.add_argument("--ablation", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--name")
    ap.add_argument("--harvest", action="store_true")
    ap.add_argument("--curate", action="store_true")
    args = ap.parse_args()
    if args.local_only and args.mode == "record":
        ap.error("never record local-only runs (use --mode live)")
    if args.harvest:
        asyncio.run(harvest(args))
        return
    if args.curate:
        curate()
        return
    out = asyncio.run(evaluate(args))
    name = args.name or ("rules" if args.rules else ("local" if args.local_only else args.mode))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(f"wrote {(RESULTS / f'{name}.json').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

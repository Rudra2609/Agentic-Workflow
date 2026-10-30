"""Verification evaluation (Sprint 6 item 6.10) on the seeded-hallucination benchmark (``samples/verify/``).

    cd backend
    uv run python -m tests.verify.eval.run_eval                          # replay (recorded answers), offline
    HMAP_LLM_RECORD_MISSING=verify uv run python -m tests.verify.eval.run_eval   # record what is missing (team keys)
    uv run python -m tests.verify.eval.run_eval --rules                  # no model at all (rule fallbacks)
    uv run python -m tests.verify.eval.run_eval --mode live --local-only --configs L1-L4+counter --no-reports
                                                                         # local qwen3.5:9b, NOT recorded

Configurations (the ablation the sprint asks for):

- ``L1``            the mechanical check only;
- ``L1+L2``         + entailment of the cited quotes;
- ``L1-L4``         + the verifier's own search (local corpus + every benchmark page) and the cross-source check;
- ``L1-L4+counter`` + the benchmark's counter-sources handed to L4 directly (upper bound for L3's recall);
- ``no-swap`` / ``no-guard`` (with ``--ablation``): L1-L4 without the position-swap control / the number guard.

Per kind: recall of flagged errors (verdict ≠ VERIFIED) and exact-verdict accuracy; on ``clean``: the false-alarm
rate; overall accuracy and Cohen's κ against the human labels; position-swap agreement; model calls and tokens; per
decision-table row: how often the verdict was right (the aggregator's confidence table). Also the 10 real Sprint 5
reports verified end to end (citation recall = share of claims VERIFIED, quote pass rate).
"""

import argparse
import asyncio
import json
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from hmap.agents.research.corpus import CORPUS_DIR, PageStore
from hmap.agents.research.fetch import Fetcher
from hmap.agents.research.model import Hit, Page
from hmap.agents.research.providers import LocalProvider
from hmap.agents.verify import benchmark as bench
from hmap.agents.verify.entail import Usage
from hmap.agents.verify.model import LAYERS, ClaimCheck, Quote, VerificationTrace
from hmap.agents.verify.pipeline import VerifyDeps, verify_report
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts import ResearchReport
from hmap.core.llm.base import LLMClient
from hmap.core.llm.gateway import Gateway

RESULTS = bench.BENCH_DIR / "eval_results"
VERDICTS = ("VERIFIED", "UNSUPPORTED", "CONFLICTING", "NEEDS_MORE_RESEARCH")


def gateway(mode: str, local_only: bool) -> LLMClient:
    settings = Settings.from_env().model_copy(update={"llm_mode": mode})
    gw = Gateway(settings).for_plugin("verify")
    return gw.local_only() if local_only else gw


_REAL_PAGES: Path | None = None


def real_pages_dir() -> Path:
    """Member 5's corpus is read in place; the REAL benchmark pages are copied once to a temporary folder."""
    global _REAL_PAGES
    if _REAL_PAGES is None:
        _REAL_PAGES = Path(tempfile.mkdtemp(prefix="verify-eval-pages-"))
        for f in sorted(bench.PAGES_DIR.glob("*.json")):
            if not f.name.startswith("synthetic-"):
                shutil.copy(f, _REAL_PAGES / f.name)
    return _REAL_PAGES


def search_store() -> PageStore:
    """The search world: Member 5's offline corpus + the real benchmark pages (no synthetic page)."""
    return PageStore([real_pages_dir(), CORPUS_DIR], write_dir=None)


def item_store(item: bench.Item, shared: PageStore) -> PageStore:
    """A contradiction item's world also holds the one synthetic page written for it ("it exists on the web");
    every other item searches the shared real world, so no planted contradiction leaks into a clean item."""
    own = [bench.PAGES_DIR / q.page.removeprefix("pages/") for q in item.counter if q.page]
    if not own:
        return shared
    extra = Path(tempfile.mkdtemp(prefix=f"verify-eval-{item.id}-"))
    for f in own:
        shutil.copy(f, extra / f.name)
    return PageStore([extra, real_pages_dir(), CORPUS_DIR], write_dir=None)


def lookup_for(store: PageStore):  # type: ignore[no-untyped-def]
    fetcher = Fetcher(store=store, mode="cached")

    async def lookup(hit: Hit) -> Page | None:
        return (await fetcher.fetch(hit)).page

    return lookup


def kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    if not n:
        return 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[v] * cb[v] for v in VERDICTS) / (n * n)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def score(items: list[bench.Item], checks: list[ClaimCheck]) -> dict[str, Any]:
    per_kind: dict[str, dict[str, Any]] = {}
    by_kind: dict[str, list[tuple[bench.Item, ClaimCheck]]] = defaultdict(list)
    for it, c in zip(items, checks, strict=True):
        by_kind[it.kind].append((it, c))
    for kind in bench.KINDS:
        rows = by_kind.get(kind, [])
        flagged = sum(1 for _, c in rows if c.verdict != "VERIFIED")
        exact = sum(1 for it, c in rows if c.verdict == it.expected)
        per_kind[kind] = {"n": len(rows), "flagged": flagged, "exact": exact,
                          "verdicts": dict(Counter(c.verdict for _, c in rows))}
        if kind == "clean":
            per_kind[kind]["false_alarm_rate"] = round(flagged / len(rows), 3) if rows else 0.0
        else:
            per_kind[kind]["recall"] = round(flagged / len(rows), 3) if rows else 0.0
    errors = [(it, c) for it, c in zip(items, checks, strict=True) if it.kind != "clean"]
    swaps = [a.l2 for c in checks for a in c.atoms if a.l2 is not None and a.l2.by == "model"
             and a.l2.swapped_label is not None]
    rows_ok: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for it, c in zip(items, checks, strict=True):
        worst = next((a for a in c.atoms if a.verdict == c.verdict and a.row != "skip"), None)
        if worst is not None:
            rows_ok[worst.row][1] += 1
            rows_ok[worst.row][0] += int(c.verdict == it.expected)
    return {
        "per_kind": per_kind,
        "accuracy": round(sum(1 for it, c in zip(items, checks, strict=True) if c.verdict == it.expected)
                          / len(items), 3),
        "error_recall": round(sum(1 for _, c in errors if c.verdict != "VERIFIED") / len(errors), 3),
        "kappa": kappa([(it.expected, c.verdict) for it, c in zip(items, checks, strict=True)]),
        "swap_agreement": round(sum(1 for j in swaps if not j.unsure) / len(swaps), 3) if swaps else None,
        "rules_judgements": sum(1 for c in checks for a in c.atoms if a.l2 is not None and a.l2.by == "rules"),
        "rows": {k: {"right": v[0], "n": v[1], "accuracy": round(v[0] / v[1], 3)} for k, v in sorted(rows_ok.items())},
    }


async def run_config(name: str, items: list[bench.Item], llm: LLMClient | None, *, layers: frozenset[str],
                     counter: bool, swap: bool = True, guard: bool = True) -> dict[str, Any]:
    store = search_store()
    usage = Usage()
    started = time.monotonic()
    sem = asyncio.Semaphore(4)

    async def one(it: bench.Item) -> ClaimCheck:
        world = item_store(it, store)
        deps = VerifyDeps(llm=llm, load_page=bench.load_page, providers=[LocalProvider(world)],
                          lookup=lookup_for(world),
                          layers=layers, swap=swap, number_guard=guard, usage=usage)
        async with sem:
            return await bench.verify_item(it, deps, use_counter=counter)

    checks = list(await asyncio.gather(*(one(it) for it in items)))
    out = score(items, checks)
    out.update({"config": name, "layers": sorted(layers), "counter_sources": counter, "swap": swap, "guard": guard,
                "model_calls": usage.calls, "tokens": usage.tokens, "failed_calls": len(usage.errors),
                "seconds": round(time.monotonic() - started, 1),
                "items": [{"id": it.id, "kind": it.kind, "expected": it.expected, "verdict": c.verdict,
                           "confidence": c.confidence, "rows": [a.row for a in c.atoms],
                           "explanation": c.explanation[:300]} for it, c in zip(items, checks, strict=True)]})
    return out


def _page_by_sha() -> dict[str, Page]:
    out = {}
    for f in bench.PAGES_DIR.glob("*.json"):
        p = Page.model_validate_json(f.read_text(encoding="utf-8"))
        out[p.content_sha256] = p
    return out


async def run_reports(llm: LLMClient | None) -> dict[str, Any]:
    """The 10 real Sprint 5 reports, end to end (all layers): how much of real research output checks out."""
    pages = _page_by_sha()

    async def load(q: Quote) -> Page | None:
        return pages.get(q.content_sha256)

    store = search_store()
    out: dict[str, Any] = {}
    totals = Counter()
    for f in sorted((bench.BENCH_DIR / "source_reports").glob("*.json")):
        report = ResearchReport.model_validate_json(f.read_text(encoding="utf-8"))
        deps = VerifyDeps(llm=llm, load_page=load, providers=[LocalProvider(store)], lookup=lookup_for(store))
        trace = VerificationTrace(task_id=report.task_id, project_id="eval")
        vr = await verify_report(report, deps, trace)
        l1 = [r for c in trace.claims for r in (c.atoms[0].l1 if c.atoms else [])]
        s = vr.summary
        totals.update(s)
        totals["claims"] += len(vr.claim_verdicts)
        totals["quotes"] += len(l1)
        totals["quotes_ok"] += sum(1 for r in l1 if r.ok)
        out[f.stem] = {"summary": s, "claims": len(vr.claim_verdicts),
                       "citation_recall": round(s["verified"] / max(1, len(vr.claim_verdicts)), 3),
                       "follow_up_questions": vr.follow_up_questions,
                       "verdicts": {v.claim_id: v.verdict for v in vr.claim_verdicts}}
    out["_total"] = {**dict(totals), "citation_recall": round(totals["verified"] / max(1, totals["claims"]), 3),
                     "quote_pass_rate": round(totals["quotes_ok"] / max(1, totals["quotes"]), 3)}
    return out


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    items = bench.load()
    if args.per_kind:
        items = [it for k in bench.KINDS for it in [i for i in items if i.kind == k][:args.per_kind]]
    llm = None if args.rules else gateway(args.mode, args.local_only)
    all_layers = frozenset(LAYERS)
    configs: list[tuple[str, dict[str, Any]]] = [
        ("L1", {"layers": frozenset({"l1"}), "counter": False}),
        ("L1+L2", {"layers": frozenset({"l1", "l2"}), "counter": False}),
        ("L1-L4", {"layers": all_layers, "counter": False}),
        ("L1-L4+counter", {"layers": all_layers, "counter": True}),
    ]
    if args.ablation:
        configs += [("no-swap", {"layers": all_layers, "counter": True, "swap": False}),
                    ("no-guard", {"layers": all_layers, "counter": True, "guard": False})]
    if args.configs:
        configs = [c for c in configs if c[0] in args.configs]
    out: dict[str, Any] = {"mode": "rules" if args.rules else args.mode, "local_only": args.local_only,
                           "items": len(items), "configs": {}}
    for name, kw in configs:
        res = await run_config(name, items, llm, **kw)
        out["configs"][name] = res
        pk = res["per_kind"]
        print(f"{name:14s} acc {res['accuracy']:.3f}  κ {res['kappa']:.3f}  error-recall {res['error_recall']:.3f}  "
              f"false-alarm {pk['clean']['false_alarm_rate']:.3f}  "
              + "  ".join(f"{k} {pk[k]['flagged']}/{pk[k]['n']}" for k in bench.KINDS if k != "clean")
              + f"  calls {res['model_calls']}  {res['seconds']}s")
    if not args.no_reports:
        out["reports"] = await run_reports(llm)
        print("real reports:", json.dumps(out["reports"]["_total"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("replay", "record", "live"), default="replay")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--rules", action="store_true", help="no model at all (rule fallbacks)")
    ap.add_argument("--ablation", action="store_true")
    ap.add_argument("--name")
    ap.add_argument("--configs", nargs="*", help="only these configurations (e.g. L1-L4+counter)")
    ap.add_argument("--no-reports", action="store_true", help="skip the 10 real reports")
    ap.add_argument("--per-kind", type=int, default=0, help="only the first N items of each kind (slow models)")
    args = ap.parse_args()
    if args.local_only and args.mode == "record":
        ap.error("never record local-only runs (use --mode live)")
    out = asyncio.run(evaluate(args))
    name = args.name or ("rules" if args.rules else ("local" if args.local_only else args.mode))
    RESULTS.mkdir(parents=True, exist_ok=True)
    path: Path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

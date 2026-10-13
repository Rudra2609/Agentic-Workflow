"""Evaluation harness for document intelligence (spec item 2.13). Runs the real pipeline on every gold document and
prints per-field precision / recall / F1, priority and marks accuracy, quote verification, OCR checks and latency.

    cd backend
    uv run python -m tests.doc_intel.eval.run_eval --mode rules            # no model: the rule pre-pass alone
    uv run python -m tests.doc_intel.eval.run_eval --mode replay           # recorded answers (no network, no keys)
    uv run python -m tests.doc_intel.eval.run_eval --mode record           # live models (cloud first), recorded
    uv run python -m tests.doc_intel.eval.run_eval --mode record --local-only   # local qwen3.5:9b + Tesseract only

Results go to ``samples/doc_intel/eval_results/<name>.json`` (``--name``, default: the mode).
"""

import argparse
import asyncio
import json
import mimetypes
import time
from typing import Any

from hmap.agents.doc_intel.cache import MemoryCache
from hmap.agents.doc_intel.loaders import InputDocument
from hmap.agents.doc_intel.pipeline import run_pipeline
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.llm.base import LLMClient
from hmap.core.llm.gateway import Gateway

from .metrics import PRF, DocScore, score_document

GOLD = REPO_ROOT / "samples" / "doc_intel" / "gold"
RESULTS = REPO_ROOT / "samples" / "doc_intel" / "eval_results"
FIELDS = ("requirements", "constraints", "deliverables", "evaluation_criteria")


def gold_cases(only: list[str] | None = None) -> list[dict[str, Any]]:
    cases = [json.loads(p.read_text()) for p in sorted((GOLD / "expected").glob("*.json"))]
    return [c for c in cases if not only or any(o in c["id"] for o in only)]


def inputs_for(case: dict[str, Any]) -> list[InputDocument]:
    docs = []
    for k, f in enumerate(case["files"], start=1):
        path = GOLD / "docs" / f["path"]
        media = mimetypes.guess_type(path.name)[0] or ""
        if path.suffix == ".docx":
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        docs.append(InputDocument(doc_id=f"doc-{k}", name=f["name"], data=path.read_bytes(), media_type=media,
                                  folder=f["folder"], path=f"{f['folder']}/{f['name']}" if f["folder"] else f["name"]))
    return docs


def make_llm(mode: str, local_only: bool) -> LLMClient | None:
    if mode == "rules":
        return None
    settings = Settings.from_env().model_copy(update={"llm_mode": mode})
    gw = Gateway(settings).for_plugin("doc_intel")
    return gw.local_only() if local_only else gw


async def run_case(case: dict[str, Any], llm: LLMClient | None, mode: str) -> tuple[DocScore, dict[str, Any]]:
    started = time.perf_counter()
    result = await run_pipeline(f"P-EVAL-{case['id']}", inputs_for(case), llm, cache=MemoryCache(),
                                use_llm=mode != "rules")
    seconds = time.perf_counter() - started
    score = score_document(case, result.requirement_set, result.document_model, seconds)
    return score, {"stats": result.stats.__dict__, "open_questions": result.requirement_set.open_questions}


def summarise(scores: list[DocScore]) -> dict[str, Any]:
    totals = {f: PRF() for f in FIELDS}
    for s in scores:
        for f in FIELDS:
            totals[f].add(s.fields[f])
    pages = sum(s.pages for s in scores)
    ocr = [s.ocr_word_accuracy for s in scores if s.ocr_word_accuracy is not None]
    return {
        "fields": {f: {"precision": round(t.precision, 3), "recall": round(t.recall, 3), "f1": round(t.f1, 3),
                       "tp": t.tp, "fp": t.fp, "fn": t.fn} for f, t in totals.items()},
        "priority_accuracy": round(sum(s.priority_correct for s in scores) / max(1, sum(s.priority_total
                                                                                         for s in scores)), 3),
        "rubric_marks_accuracy": round(sum(s.marks_correct for s in scores) / max(1, sum(s.marks_total
                                                                                          for s in scores)), 3),
        "total_marks_correct": f"{sum(s.total_marks_ok for s in scores)}/{len(scores)}",
        "quote_verified_rate": round(sum(s.quotes_verified for s in scores) / max(1, sum(s.quotes_total
                                                                                         for s in scores)), 3),
        "ocr_gate_correct": f"{sum(s.ocr_gate_ok for s in scores)}/{len(scores)}",
        "ocr_word_accuracy": round(sum(ocr) / len(ocr), 3) if ocr else None,
        "heading_recall": round(sum(s.heading_recall for s in scores) / max(1, len(scores)), 3),
        "seconds_total": round(sum(s.seconds for s in scores), 1),
        "seconds_per_page": round(sum(s.seconds for s in scores) / max(1, pages), 2),
    }


def print_table(scores: list[DocScore], summary: dict[str, Any]) -> None:
    print(f"\n{'document':20s} {'req F1':>7s} {'con F1':>7s} {'del F1':>7s} {'crit F1':>7s} {'marks':>6s} "
          f"{'total':>6s} {'quotes':>7s} {'ocr':>5s} {'sec':>6s}")
    for s in scores:
        f = s.fields
        quotes = f"{s.quotes_verified}/{s.quotes_total}"
        marks = f"{s.marks_correct}/{s.marks_total}"
        print(f"{s.doc_id:20s} {f['requirements'].f1:7.2f} {f['constraints'].f1:7.2f} {f['deliverables'].f1:7.2f} "
              f"{f['evaluation_criteria'].f1:7.2f} {marks:>6s} {'ok' if s.total_marks_ok else 'no':>6s} "
              f"{quotes:>7s} {'ok' if s.ocr_gate_ok else 'no':>5s} {s.seconds:6.1f}")
    print("\nOverall:")
    for name, v in summary["fields"].items():
        print(f"  {name:20s} P {v['precision']:.2f}  R {v['recall']:.2f}  F1 {v['f1']:.2f}  "
              f"(tp {v['tp']}, fp {v['fp']}, fn {v['fn']})")
    for key in ("priority_accuracy", "rubric_marks_accuracy", "total_marks_correct", "quote_verified_rate",
                "ocr_gate_correct", "ocr_word_accuracy", "heading_recall", "seconds_total", "seconds_per_page"):
        print(f"  {key:22s} {summary[key]}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["rules", "replay", "record", "live"], default="replay")
    ap.add_argument("--local-only", action="store_true", help="never use the cloud (local model and Tesseract)")
    ap.add_argument("--only", nargs="*", help="gold ids (substring match)")
    ap.add_argument("--name", help="results file name (default: the mode)")
    ap.add_argument("--verbose", action="store_true", help="list missed and extra items")
    args = ap.parse_args()
    llm = make_llm(args.mode, args.local_only)
    scores: list[DocScore] = []
    details: dict[str, Any] = {}
    for case in gold_cases(args.only):
        score, info = await run_case(case, llm, args.mode)
        scores.append(score)
        details[case["id"]] = {"misses": score.misses, "extras": score.extras, **info}
        if args.verbose:
            print(f"\n{case['id']}: missed {score.misses}\n  extra {score.extras}")
    if isinstance(llm, Gateway):
        await llm.aclose()
    summary = summarise(scores)
    print_table(scores, summary)
    name = args.name or (args.mode + ("-local" if args.local_only else ""))
    RESULTS.mkdir(parents=True, exist_ok=True)
    per_doc = {s.doc_id: {"fields": {f: {"f1": round(p.f1, 3), "tp": p.tp, "fp": p.fp, "fn": p.fn}
                                     for f, p in s.fields.items()},
                          "marks": f"{s.marks_correct}/{s.marks_total}", "total_marks_ok": s.total_marks_ok,
                          "quotes": f"{s.quotes_verified}/{s.quotes_total}", "ocr_gate_ok": s.ocr_gate_ok,
                          "ocr_word_accuracy": s.ocr_word_accuracy, "heading_recall": round(s.heading_recall, 3),
                          "seconds": round(s.seconds, 2), **details[s.doc_id]} for s in scores}
    (RESULTS / f"{name}.json").write_text(json.dumps({"mode": args.mode, "local_only": args.local_only,
                                                      "summary": summary, "documents": per_doc}, indent=2) + "\n")
    print(f"\nwrote {(RESULTS / f'{name}.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

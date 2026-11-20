"""Coding evaluation (Sprint 7 item 7.13) on the mini benchmark (``samples/coding/tasks``, 18 tasks with hidden tests).

    cd backend
    uv run python -m tests.coding.eval.run_eval                               # replay (recorded answers), offline
    HMAP_LLM_RECORD_MISSING=coding uv run python -m tests.coding.eval.run_eval    # record what is missing (team keys)
    uv run python -m tests.coding.eval.run_eval --mode live --local-only --name local   # local qwen3.5:9b, NOT recorded
    uv run python -m tests.coding.eval.run_eval --role reasoner --name reasoner   # the reasoner route as the coder
    uv run python -m tests.coding.eval.run_eval --samples 3 --name pass3      # + pass@3 (3 samples at T=0.6)
    uv run python -m tests.coding.eval.run_eval --ablation                    # + no-locator / no-debug / bm25-only

Per task: the agent's loop runs on the task's starter (an EMPTY workspace for the greenfield-from-template tasks:
the agent picks the template), then the task's **hidden tests** run in the jailed runner. Reported: pass@1 (seed 7,
temperature 0), pass@k (unbiased estimator, Chen et al. 2021) when ``--samples`` > 0, edit-apply rate (first try /
after feedback), debug rounds, model calls, tokens, seconds, locator top-1 / top-3 (modify / bug-fix / decoy), the
template chosen for the template tasks. Every passing run's prompts and answers go to
``samples/coding/trajectories/<name>/<task>.json`` (fine-tune / benchmark data for Member 11; no keys, no paths).
"""

import argparse
import asyncio
import json
import math
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from hmap.agents.coding.loop import CodingLoop, Job, Options
from hmap.agents.coding.model import CodingTrace
from hmap.agents.coding.prompts import TaskView
from hmap.agents.coding.tools.runner import Runner
from hmap.agents.coding.workspace import Workspace
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.llm.base import LLMClient, LLMResponse, Message
from hmap.core.llm.gateway import Gateway

BENCH = REPO_ROOT / "samples" / "coding"
TASKS = BENCH / "tasks"
RESULTS = BENCH / "eval_results"
TRAJECTORIES = BENCH / "trajectories"
CONFIGS: dict[str, dict[str, Any]] = {
    "full": {},
    "no-locator": {"use_locator": False},
    "no-debug": {"use_debug": False},
    "bm25-only": {"use_embeddings": False, "use_rerank": False},
}


class RecordingLLM:
    """Keeps every chat call's messages and answer (the trajectory of one task)."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.turns: list[dict[str, Any]] = []

    async def generate(self, role: Any, messages: Any, **kw: Any) -> LLMResponse:
        resp = await self.inner.generate(role, messages, **kw)
        msgs = [m if isinstance(m, Message) else Message.model_validate(m) for m in messages]
        self.turns.append({"role": str(role), "schema": getattr(kw.get("schema"), "__name__", None),
                           "messages": [m.model_dump() for m in msgs], "answer": resp.text,
                           "tokens": resp.usage.input_tokens + resp.usage.output_tokens, "model": resp.usage.model})
        return resp

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.inner.embed(texts)

    async def classify(self, state: str, questions: Any) -> Any:
        return await self.inner.classify(state, questions)

    async def read_images(self, prompt: str, images: list[bytes], **kw: Any) -> LLMResponse:
        return await self.inner.read_images(prompt, images, **kw)


def gateway(mode: str, local_only: bool) -> LLMClient:
    settings = Settings.from_env().model_copy(update={"llm_mode": mode})
    gw = Gateway(settings).for_plugin("coding")
    return gw.local_only() if local_only else gw


def tasks(only: list[str] | None) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for d in sorted(p for p in TASKS.iterdir() if (p / "task.json").exists()):
        meta = json.loads((d / "task.json").read_text())
        if not only or meta["id"] in only:
            out.append((d, meta))
    return out


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k from n samples with c correct (Chen et al. 2021)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))


async def run_task(task_dir: Path, meta: dict[str, Any], llm: LLMClient, settings: Settings, options: Options,
                   work: Path) -> dict[str, Any]:
    root = work / f"{meta['id']}-{options.seed}"
    if root.exists():
        shutil.rmtree(root)
    if meta.get("template"):
        root.mkdir(parents=True)                       # empty: the agent picks the template itself
    else:
        shutil.copytree(task_dir / "starter", root)
    ws = Workspace(root)
    rec = RecordingLLM(llm)
    trace = CodingTrace(task_id=meta["id"], project_id="eval", capability="code.implement")
    job = Job(ws=ws, settings=settings, trace=trace, llm=rec,  # type: ignore[arg-type]
              task=TaskView(objective=meta["objective"], criteria=meta["acceptance_criteria"]), options=options)
    t0 = time.monotonic()
    error = None
    try:
        await CodingLoop(job).run()
    except Exception as exc:  # report, keep going
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    seconds = round(time.monotonic() - t0, 1)
    for f in (task_dir / "hidden_tests").iterdir():
        shutil.copy(f, root / f.name)
    res = await Runner(ws, settings).run(["python", "-m", "unittest", "discover", "-p", "test_*.py"], timeout=60)
    edits = [e for e in trace.edits if e.files or e.error]
    located = [x["path"] for x in trace.located]
    want = set(meta.get("files_to_edit") or [])
    out: dict[str, Any] = {
        "task": meta["id"], "kind": meta["kind"], "decoy": bool(meta.get("decoy")),
        "template_task": meta.get("template"), "template_chosen": trace.template, "passed": res.ok,
        "hidden_tail": res.output.strip().splitlines()[-1:] if res.output else [], "outcome": trace.outcome,
        "stop": trace.stop_reason, "model_calls": trace.model_calls, "tokens": trace.tokens, "seconds": seconds,
        "edits": len(edits), "edits_ok": sum(e.ok for e in edits), "first_edit_ok": bool(edits and edits[0].ok),
        "debug_rounds": sum(s.kind == "debug" for s in trace.steps),
        "top1": bool(located and located[0] in want) if want and meta["kind"] != "greenfield" else None,
        "top3": (want <= set(located[:3])) if want and meta["kind"] != "greenfield" else None,
        "files_changed": trace.files_changed, "error": error, "seed": options.seed,
    }
    out["_trajectory"] = {"task": meta["id"], "objective": meta["objective"], "criteria": meta["acceptance_criteria"],
                          "turns": rec.turns, "files_changed": trace.files_changed, "passed": res.ok}
    return out


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(xs: list[bool]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    kinds: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = "template" if r["template_task"] else ("decoy" if r["decoy"] else r["kind"])
        kinds.setdefault(key, []).append(r)
    edits = sum(r["edits"] for r in rows)
    loc = [r for r in rows if r["top1"] is not None]
    return {
        "tasks": len(rows), "pass@1": rate([r["passed"] for r in rows]),
        "by_kind": {k: {"n": len(v), "pass@1": rate([r["passed"] for r in v])} for k, v in sorted(kinds.items())},
        "edit_apply_rate": round(sum(r["edits_ok"] for r in rows) / edits, 3) if edits else None,
        "first_edit_ok": rate([r["first_edit_ok"] for r in rows if r["edits"]]),
        "locator_top1": rate([bool(r["top1"]) for r in loc]), "locator_top3": rate([bool(r["top3"]) for r in loc]),
        "locator_top1_decoy": rate([bool(r["top1"]) for r in loc if r["decoy"]]),
        "locator_top3_decoy": rate([bool(r["top3"]) for r in loc if r["decoy"]]),
        "template_right": rate([r["template_chosen"] == r["template_task"] for r in rows if r["template_task"]]),
        "mean_model_calls": round(sum(r["model_calls"] for r in rows) / len(rows), 2) if rows else None,
        "mean_tokens": round(sum(r["tokens"] for r in rows) / len(rows)) if rows else None,
        "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1) if rows else None,
        "mean_debug_rounds": round(sum(r["debug_rounds"] for r in rows) / len(rows), 2) if rows else None,
        "errors": [f"{r['task']}: {r['error']}" for r in rows if r["error"]],
    }


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    llm = gateway(args.mode, args.local_only)
    work = Path(tempfile.mkdtemp(prefix="hmap-coding-eval-"))
    settings = Settings.from_env().model_copy(update={"coding_work_dir": work})
    configs = ["full", *([c for c in CONFIGS if c != "full"] if args.ablation else [])]
    out: dict[str, Any] = {"mode": args.mode, "local_only": args.local_only, "role": args.role, "configs": {}}
    selected = tasks(args.tasks)
    for name in configs:
        options = Options(role=args.role, **CONFIGS[name])
        rows = []
        for task_dir, meta in selected:
            row = await run_task(task_dir, meta, llm, settings, options, work)
            rows.append(row)
            print(f"{name:10s} {meta['id']:24s} {'PASS' if row['passed'] else 'fail':4s} calls={row['model_calls']:2d} "
                  f"tok={row['tokens']:6d} {row['seconds']:5.1f}s stop={row['stop']}", flush=True)
        out["configs"][name] = {"summary": summarise(rows), "tasks": [{k: v for k, v in r.items() if k[0] != "_"}
                                                                      for r in rows]}
        if name == "full" and args.trajectories:
            folder = TRAJECTORIES / args.name
            folder.mkdir(parents=True, exist_ok=True)
            for r in rows:
                if r["passed"]:
                    (folder / f"{r['task']}.json").write_text(json.dumps(r["_trajectory"], indent=1) + "\n")
    if args.samples > 0:
        per_task: dict[str, list[bool]] = {}
        for seed in range(1, args.samples + 1):
            options = Options(role=args.role, seed=seed, temperature=0.6)
            for task_dir, meta in selected:
                row = await run_task(task_dir, meta, llm, settings, options, work)
                per_task.setdefault(meta["id"], []).append(row["passed"])
        n = args.samples
        out["pass@k"] = {f"pass@{k}": round(sum(pass_at_k(n, sum(v), k) for v in per_task.values()) / len(per_task),
                                            3) for k in (1, n) if k <= n}
        out["pass@k"]["samples"] = n
        out["pass@k"]["per_task"] = {t: sum(v) for t, v in per_task.items()}
    shutil.rmtree(work, ignore_errors=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("replay", "record", "live"), default="replay")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--role", default="coder", choices=("coder", "reasoner"))
    ap.add_argument("--ablation", action="store_true")
    ap.add_argument("--samples", type=int, default=0, help="pass@k samples per task (temperature 0.6)")
    ap.add_argument("--tasks", nargs="*", help="only these task ids")
    ap.add_argument("--name")
    ap.add_argument("--no-trajectories", dest="trajectories", action="store_false")
    args = ap.parse_args()
    if args.local_only and args.mode == "record":
        ap.error("never record local-only runs (use --mode live)")
    args.name = args.name or ("local" if args.local_only else f"{args.mode}-{args.role}")
    out = asyncio.run(evaluate(args))
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.name}.json"
    path.write_text(json.dumps(out, indent=1, default=str) + "\n")
    for name, cfg in out["configs"].items():
        s = cfg["summary"]
        print(f"[{name}] pass@1 {s['pass@1']} by kind {s['by_kind']} edit-apply {s['edit_apply_rate']} "
              f"locator top1/top3 {s['locator_top1']}/{s['locator_top3']} (decoy {s['locator_top1_decoy']}/"
              f"{s['locator_top3_decoy']}) template {s['template_right']} calls {s['mean_model_calls']} "
              f"tokens {s['mean_tokens']} secs {s['mean_seconds']}")
    if "pass@k" in out:
        print(f"pass@k {out['pass@k']}")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

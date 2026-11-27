"""Every member's gold set as a benchmark (item 11.5): M2 F1, M3 validity, M4 taxonomy, M5 fact coverage, M6
detection, M7 pass@1, M10 judge agreement.

Each set runs through **its owner's evaluator** (``tests/<member>/eval/``), unchanged, with every chat role on the
model under test (:func:`common.env_for`), in ``live`` mode (never records). The evaluator runs in a child process
(:func:`run_child`) whose results folder is pointed at ``samples/models/bench/sets/<model>/`` so no member's own
``eval_results`` is touched. A set that fails, times out or has no model answer is reported as such, never as a
score.

    uv run python -m hmap.agents.models.bench.run sets --models groq:qwen/qwen3.8-27b --sets m6_verify m10_judge
"""

import asyncio
import importlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hmap.agents.models.bench.common import ROOT, SAMPLES, env_for, is_cloud, slug
from hmap.core.config import Settings

SETS_OUT = SAMPLES / "bench" / "sets"


def _get(d: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


@dataclass(frozen=True)
class GoldSet:
    name: str
    member: int
    module: str
    args: tuple[str, ...]
    result_file: str
    role: str
    task: str
    score: Callable[[dict[str, Any]], float | None]
    patch: tuple[str, ...] = ("RESULTS",)
    local_flag: bool = True                       # the evaluator has --local-only
    extra: Callable[[dict[str, Any]], dict[str, Any]] = field(default=lambda d: {})


def _kappa01(k: Any) -> float | None:
    return None if k is None else max(0.0, float(k))   # BenchmarkResult.quality_score is 0-1; κ < 0 -> 0


GOLD_SETS: dict[str, GoldSet] = {s.name: s for s in [
    GoldSet("m2_extraction", 2, "tests.doc_intel.eval.run_eval", ("--mode", "live", "--name", "bench"), "bench.json",
            "reasoner", "requirement extraction (F1)", lambda d: _get(d, "summary", "fields", "requirements", "f1"),
            extra=lambda d: {"priority_accuracy": _get(d, "summary", "priority_accuracy")}),
    GoldSet("m3_planning", 3, "tests.planning.eval.run_eval", ("--mode", "live", "--name", "bench"), "bench.json",
            "reasoner", "plan validity", lambda d: _get(d, "summary", "validity"),
            extra=lambda d: {"steps_f1": _get(d, "summary", "steps", "f1"),
                             "fallbacks": _get(d, "summary", "fallbacks")}),
    GoldSet("m4_taxonomy", 4, "tests.refine.eval.taxonomy_eval", ("--mode", "live"), "taxonomy.json", "classify",
            "issue category (accuracy)", lambda d: _get(d, "model", "accuracy"), local_flag=False,
            extra=lambda d: {"failed": _get(d, "model", "failed")}),
    GoldSet("m5_research", 5, "tests.research.eval.run_eval", ("--mode", "live", "--name", "bench"), "bench.json",
            "reasoner", "research fact coverage", lambda d: _get(d, "conditions", "hybrid", "summary", "fact_coverage"),
            extra=lambda d: {"citation_validity": _get(d, "conditions", "hybrid", "summary", "citation_validity")}),
    GoldSet("m6_verify", 6, "tests.verify.eval.run_eval",
            ("--mode", "live", "--name", "bench", "--configs", "L1-L4+counter"), "bench.json", "judge",
            "claim verification (accuracy)", lambda d: _get(d, "configs", "L1-L4+counter", "accuracy"),
            extra=lambda d: {"kappa": _get(d, "configs", "L1-L4+counter", "kappa"),
                             "error_recall": _get(d, "configs", "L1-L4+counter", "error_recall")}),
    GoldSet("m7_coding", 7, "tests.coding.eval.run_eval", ("--mode", "live", "--name", "bench", "--no-trajectories"),
            "bench.json", "coder", "coding pass@1", lambda d: _get(d, "configs", "full", "summary", "pass@1"),
            patch=("RESULTS", "TRAJECTORIES"),
            extra=lambda d: {"edit_apply_rate": _get(d, "configs", "full", "summary", "edit_apply_rate")}),
    GoldSet("m10_judge", 10, "tests.review.eval.run_eval", ("--judge", "--mode", "live", "--name", "bench"),
            "bench.json", "judge", "review judge agreement (κ, judge alone)",
            lambda d: _kappa01(_get(d, "judge_only", "kappa")), patch=("OUT",),
            extra=lambda d: {"accuracy": _get(d, "judge_only", "accuracy"),
                             "fail_as_pass": _get(d, "judge_only", "fail_as_pass")}),
]}


def child_main(argv: list[str]) -> int:
    """In the child: ``<module> <out dir> <patched names,...> -- <evaluator args>``."""
    module_name, out_dir, names, _, *args = argv
    mod = importlib.import_module(module_name)
    for name in names.split(","):
        setattr(mod, name, Path(out_dir) / ("trajectories" if name == "TRAJECTORIES" else ""))
    sys.argv = [module_name, *args]
    result = mod.main()
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return int(result or 0)


def run_child(gold: GoldSet, model: str, out_dir: Path, *, timeout_s: float,
              base_env: dict[str, str]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    args = list(gold.args) + (["--local-only"] if gold.local_flag and not is_cloud(model) else [])
    env = {**base_env, **env_for(model, Settings()), "HMAP_LLM_MODE": "live", "HMAP_RESEARCH_MODE": "cached"}
    cmd = [sys.executable, "-m", "hmap.agents.models.bench.sets", gold.module, str(out_dir), ",".join(gold.patch),
           "--", *args]
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=ROOT / "backend", env=env, capture_output=True, text=True, timeout=timeout_s,
                           check=False)
        status = "ok" if p.returncode == 0 else f"exit {p.returncode}"
        tail = (p.stdout + p.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        status, tail = f"timeout after {timeout_s:.0f} s", ""
    seconds = round(time.monotonic() - started, 1)
    path = out_dir / gold.result_file
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() and status == "ok" else None
    score = gold.score(data) if data is not None else None
    return {"set": gold.name, "member": gold.member, "model": model, "role": gold.role, "task": gold.task,
            "status": status if score is not None or status != "ok" else "no score", "score": score,
            "extra": gold.extra(data) if data is not None else {}, "seconds": seconds,
            "log_tail": tail if status != "ok" else ""}


def run_sets(models: list[str], names: list[str], *, timeout_s: float = 1200.0) -> list[dict[str, Any]]:
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("HMAP_")}
    base_env["HMAP_ENV_FILE"] = os.environ.get("HMAP_ENV_FILE", "")
    out = []
    for model in models:
        for name in names:
            res = run_child(GOLD_SETS[name], model, SETS_OUT / slug(model) / name, timeout_s=timeout_s,
                            base_env=base_env)
            out.append(res)
            (SETS_OUT / slug(model)).mkdir(parents=True, exist_ok=True)
            (SETS_OUT / slug(model) / f"{name}.summary.json").write_text(json.dumps(res, indent=1) + "\n")
            print(f"{model:32} {name:14} {res['status']:>20}  score {res['score']}  ({res['seconds']} s)", flush=True)
    return out


if __name__ == "__main__":
    raise SystemExit(child_main(sys.argv[1:]))

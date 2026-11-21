"""Testing evaluation (Sprint 8 item 8.13).

    cd backend
    uv run python -m tests.testing.eval.run_eval                         # detection on both backends (Docker if up)
    uv run python -m tests.testing.eval.run_eval --loop                  # + loop fix rate (replay: recorded answers)
    HMAP_LLM_RECORD_MISSING=testing uv run python -m tests.testing.eval.run_eval --loop --mode replay   # record (keys)
    uv run python -m tests.testing.eval.run_eval --loop --mode live --local-only --name local         # local model

Three sets:

1. **Seeded** (``samples/testing/seeded_failures``): the known-good module + 15 variants with one labelled fault.
   Detection rate, false-pass rate on the good version, classification accuracy.
2. **Unseen** (Member 7's benchmark: 3 bug-fix + 3 decoy bug-fix + 3 modify tasks): each starter with the task's
   hidden tests must FAIL (the bug / the missing feature is there), and the same starter with the gold fix applied
   must PASS (no false alarm). The rules were never tuned on these.
3. **Loop** (``--loop``): each seeded variant with an actionable failure goes through Member 7's coding loop as a
   revision (the testing agent's required changes + failures), then is tested again, up to 2 rounds (the agent's
   default). Fixed = every stage passes and the test file was not touched.

4. **Extras** (``--extras``, Docker): mutation score of the seeded suite's tests (how many planted faults they catch),
   JS/TS detection on a small labelled set (good, wrong result, syntax, crash, eval, lint, TS type error), fuzzing on
   functions with known edge-case bugs (and one that rejects bad input correctly).

Also: sandbox overhead (seconds per pipeline run, Docker vs local).
Results: ``samples/testing/eval_results/<name>.json``.
"""

import argparse
import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from hmap.agents.coding import debug
from hmap.agents.coding.edits import apply_text
from hmap.agents.coding.loop import CodingLoop, Job
from hmap.agents.coding.model import CodingTrace
from hmap.agents.coding.prompts import TaskView
from hmap.agents.coding.workspace import Workspace
from hmap.agents.testing.model import FailureRecord
from hmap.agents.testing.pipeline import PipelineResult, run_pipeline
from hmap.agents.testing.refine_loop import actionable, required_changes
from hmap.agents.testing.sandbox import Backend
from hmap.agents.testing.sandbox.docker import DockerBackend, docker_ready
from hmap.agents.testing.sandbox.local import LocalBackend
from hmap.agents.testing.stages import View
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.llm.base import LLMClient
from hmap.core.llm.gateway import Gateway

SEEDED = REPO_ROOT / "samples" / "testing" / "seeded_failures"
TASKS = REPO_ROOT / "samples" / "coding" / "tasks"
UNSEEN = ["b1_unframe_off_by_one", "b2_broadcast_crash", "b3_median_even", "d1_discount_percent",
          "d2_session_minutes", "d3_csv_quotes", "m1_who_command", "m2_json_format", "m3_max_clients"]
RESULTS = REPO_ROOT / "samples" / "testing" / "eval_results"
LOOP_OBJECTIVE = ("Fix the chat protocol module chatproto.py so that its tests (test_chatproto.py) and the security "
                  "checks pass. Do not change the tests.")
STAGE_TIMEOUT = 20.0


def verdict(r: PipelineResult) -> str:
    counted = [f for f in r.failures if f.category != "LINT" and not f.flaky]
    if counted:
        return counted[0].category
    return "LINT" if r.failures else "PASS"


def seeded_cases() -> list[tuple[str, str, dict[str, str]]]:
    labels = json.loads((SEEDED / "labels.json").read_text(encoding="utf-8"))
    test = (SEEDED / "good" / "test_chatproto.py").read_text(encoding="utf-8")
    good = (SEEDED / "good" / "chatproto.py").read_text(encoding="utf-8")
    out = [("good", "PASS", {"chatproto.py": good, "test_chatproto.py": test})]
    for row in labels:
        out.append((row["variant"], row["category"],
                    {"chatproto.py": (SEEDED / "variants" / row["variant"] / "chatproto.py").read_text(),
                     "test_chatproto.py": test}))
    return out


def read_tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def unseen_cases() -> list[tuple[str, dict[str, str], dict[str, str]]]:
    """(task id, starter + hidden tests, gold-fixed starter + hidden tests)."""
    out = []
    for tid in UNSEEN:
        task = TASKS / tid
        hidden = read_tree(task / "hidden_tests")
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(task / "starter", Path(tmp) / "ws")
            ws = Workspace(Path(tmp) / "ws")
            before = read_tree(ws.root)
            apply_text(ws, (task / "gold.edits").read_text(encoding="utf-8"))
            gold = read_tree(ws.root)
        out.append((tid, {**before, **hidden}, {**gold, **hidden}))
    return out


async def detection(backend: Backend) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name, expected, files in seeded_cases():
        r = await run_pipeline(View(files=files, backend=backend.name, stage_timeout=STAGE_TIMEOUT), backend,
                               flaky_check=False)
        got = verdict(r)
        rows.append({"set": "seeded", "case": name, "expected": expected, "got": got, "seconds": r.seconds,
                     "coverage": r.coverage, "hint": next((f.hint for f in r.failures), None)})
    for tid, starter, gold in unseen_cases():
        for kind, files in (("starter", starter), ("gold", gold)):
            r = await run_pipeline(View(files=files, backend=backend.name, stage_timeout=STAGE_TIMEOUT), backend,
                                   flaky_check=False)
            got = verdict(r)
            rows.append({"set": "unseen", "case": f"{tid}/{kind}", "expected": "FAIL" if kind == "starter" else "PASS",
                         "got": got, "seconds": r.seconds, "located": [f"{f.file}:{f.line}" for f in r.failures[:2]]})
    seeded = [r for r in rows if r["set"] == "seeded"]
    bad = [r for r in seeded if r["expected"] != "PASS"]
    unseen_bad = [r for r in rows if r["set"] == "unseen" and r["expected"] == "FAIL"]
    unseen_good = [r for r in rows if r["set"] == "unseen" and r["expected"] == "PASS"]
    good = [r for r in seeded if r["expected"] == "PASS"]
    return {
        "backend": backend.name,
        "seeded_detection": round(sum(r["got"] != "PASS" for r in bad) / len(bad), 3),
        "seeded_classification": round(sum(r["got"] == r["expected"] for r in seeded) / len(seeded), 3),
        "seeded_false_pass_on_good": sum(r["got"] not in ("PASS", "LINT") for r in good),
        "unseen_detection": round(sum(r["got"] not in ("PASS", "LINT") for r in unseen_bad) / len(unseen_bad), 3),
        "unseen_false_alarms_on_gold": sum(r["got"] not in ("PASS", "LINT") for r in unseen_good),
        "seconds_per_run": round(sum(r["seconds"] for r in rows) / len(rows), 2),
        "rows": rows,
    }


async def revise_once(files: dict[str, str], failures: list[FailureRecord], llm: LLMClient,
                      settings: Settings, work: Path, n: int) -> dict[str, str]:
    root = work / f"rev-{n}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ws = Workspace(root)
    for rel, text in files.items():
        ws.write(rel, text)
    trace = CodingTrace(task_id=f"loop-{n}", project_id="eval", capability="code.revise")
    view = TaskView(objective=LOOP_OBJECTIVE, criteria=["all tests in test_chatproto.py pass",
                                                        "no insecure code (eval, shell commands, hard-coded secrets)"],
                    required_changes=required_changes(failures), kind="revise")
    known = debug.from_test_report([f.model_dump() for f in actionable(failures)])
    await CodingLoop(Job(ws=ws, settings=settings, trace=trace, task=view, llm=llm, known_failures=known)).run()
    return ws.snapshot()          # the code only: not the agent's own .tmp/ helper scripts


async def loop_rate(backend: Backend, llm: LLMClient, settings: Settings, max_rounds: int,
                    only: list[str] | None = None) -> dict[str, Any]:
    rows = []
    with tempfile.TemporaryDirectory(prefix="hmap-testing-eval-") as tmp:
        for i, (name, expected, files) in enumerate(seeded_cases()):
            if expected in ("PASS", "LINT") or (only and name not in only):
                continue
            current = dict(files)
            started = time.monotonic()
            history = []
            fixed = touched = False
            for round_ in range(max_rounds + 1):
                r = await run_pipeline(View(files=current, backend=backend.name, stage_timeout=STAGE_TIMEOUT),
                                       backend, flaky_check=False)
                history.append(verdict(r))
                if r.passed and not any(f.category == "SECURITY" for f in r.failures):
                    fixed = True
                    break
                if round_ == max_rounds or not actionable(r.failures):
                    break
                try:
                    current = await revise_once(current, r.failures, llm, settings, Path(tmp), i * 10 + round_)
                except Exception as exc:     # a replay miss or a model error ends this case
                    history.append(f"error: {type(exc).__name__}")
                    break
            touched = current.get("test_chatproto.py") != files["test_chatproto.py"]
            rows.append({"case": name, "category": expected, "fixed": fixed and not touched, "tests_edited": touched,
                         "rounds": len([h for h in history if not h.startswith("error")]) - 1, "history": history,
                         "seconds": round(time.monotonic() - started, 1)})
    return {"fix_rate": round(sum(bool(r["fixed"]) for r in rows) / len(rows), 3), "cases": len(rows), "rows": rows}


JS_BASE = {"package.json": '{"name": "x", "type": "module"}',
           "sum.js": "export function sum(a, b) {\n  return a + b;\n}\n",
           "sum.test.js": ("import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
                           "import { sum } from './sum.js';\n\n"
                           "test('adds', () => {\n  assert.equal(sum(2, 3), 5);\n});\n")}
JS_CASES = [("good", {}, "PASS"),
            ("wrong", {"sum.js": "export function sum(a, b) {\n  return a - b;\n}\n"}, "ASSERTION"),
            ("syntax", {"sum.js": "export function sum(a, b) {\n  return a + ;\n}\n"}, "SYNTAX"),
            ("crash", {"sum.js": "export function sum(a, b) {\n  return a.b.c + b;\n}\n"}, "CRASH"),
            ("eval", {"sum.js": "export function sum(a, b) {\n  return eval(a + '+' + b);\n}\n"}, "SECURITY"),
            ("lint", {"sum.js": "export function sum(a, b) {\n  const unused = 1;\n  return a + b;\n}\n"}, "LINT"),
            ("ts_type", {"util.ts": "export const n: number = 'x';\n"}, "LINT")]
FUZZ_CODE = ("def mean(values: list[int]) -> float:\n    return sum(values) / len(values)\n\n\n"
             "def first_word(text: str) -> str:\n    return text.split()[0]\n\n\n"
             "def initials(name: str) -> str:\n    return ''.join(p[0] for p in name.split(' '))\n\n\n"
             "class BadInput(Exception):\n    pass\n\n\n"
             "def safe_first(text: str) -> str:\n    if not text.split():\n        raise BadInput('empty')\n"
             "    return text.split()[0]\n")
FUZZ_EXPECTED = {"calc.mean": "ZeroDivisionError", "calc.first_word": "IndexError", "calc.initials": "IndexError"}


async def extras(settings: Settings) -> dict[str, Any]:
    from hmap.agents.testing.agent import run_fuzz, run_mutation

    docker = DockerBackend(settings)
    out: dict[str, Any] = {}
    st = settings.model_copy(update={"testing_mutants": 30})
    good = dict(seeded_cases()[0][2])
    m = await run_mutation(View(files=good, backend="docker", stage_timeout=STAGE_TIMEOUT), docker, st)
    out["mutation_seeded_tests"] = m.as_dict()
    rows = []
    for name, change, expected in JS_CASES:
        files = {**JS_BASE, **change}
        r = await run_pipeline(View(files=files, backend="docker", stage_timeout=30, language="js",
                                    image=settings.testing_image_node), docker, flaky_check=False)
        rows.append({"case": name, "expected": expected, "got": verdict(r), "seconds": r.seconds})
    out["js"] = {"classification": round(sum(r["got"] == r["expected"] for r in rows) / len(rows), 3), "rows": rows}
    summary, found = await run_fuzz(View(files={"calc.py": FUZZ_CODE}, backend="docker", stage_timeout=60), docker)
    got = {f.test.removeprefix("fuzz::") if f.test else "": f.message for f in found}
    out["fuzz"] = {"summary": summary, "found": {k: v[:160] for k, v in got.items()},
                   "expected_found": sum(e in got.get(k, "") for k, e in FUZZ_EXPECTED.items()),
                   "expected": len(FUZZ_EXPECTED), "false_findings": [k for k in got if k not in FUZZ_EXPECTED]}
    return out


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings.from_env().model_copy(update={"testing_stage_timeout_s": STAGE_TIMEOUT})
    backends: list[Backend] = []
    if args.backend in ("docker", "both") and await docker_ready(settings.testing_image):
        backends.append(DockerBackend(settings))
    if args.backend in ("local", "both"):
        backends.append(LocalBackend(settings))
    out: dict[str, Any] = {"name": args.name, "detection": [await detection(b) for b in backends]}
    if args.extras and any(b.name == "docker" for b in backends):
        out["extras"] = await extras(settings)
    if args.loop:
        gw = Gateway(settings.model_copy(update={"llm_mode": args.mode})).for_plugin("testing")
        llm = gw.local_only() if args.local_only else gw
        out["loop"] = await loop_rate(backends[0], llm, settings, args.rounds, args.cases)
        out["loop"]["backend"] = backends[0].name
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("docker", "local", "both"), default="both")
    ap.add_argument("--loop", action="store_true", help="also measure the test -> revise loop (needs a model)")
    ap.add_argument("--extras", action="store_true", help="mutation score, JS/TS detection, fuzzing (Docker)")
    ap.add_argument("--mode", choices=("replay", "live"), default="replay")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--cases", nargs="*", help="only these seeded variants in the loop (the local model is slow)")
    ap.add_argument("--name", default="eval")
    args = ap.parse_args()
    res = asyncio.run(evaluate(args))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{args.name}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    for d in res["detection"]:
        print(f"[{d['backend']}] seeded detection {d['seeded_detection']:.0%}, classification "
              f"{d['seeded_classification']:.0%}, false-pass on good {d['seeded_false_pass_on_good']}; unseen "
              f"detection {d['unseen_detection']:.0%}, false alarms on gold {d['unseen_false_alarms_on_gold']}; "
              f"{d['seconds_per_run']} s per run")
    if "extras" in res:
        ex = res["extras"]
        mu = ex["mutation_seeded_tests"]
        print(f"[extras] mutation: {mu['killed']}/{mu['total']} planted faults caught; JS/TS classification "
              f"{ex['js']['classification']:.0%}; fuzz: {ex['fuzz']['expected_found']}/{ex['fuzz']['expected']} known "
              f"bugs found, false findings {ex['fuzz']['false_findings']}")
    if "loop" in res:
        lp = res["loop"]
        print(f"[loop/{lp['backend']}] fixed {lp['fix_rate']:.0%} of {lp['cases']} seeded variants")
        for r in lp["rows"]:
            print(f"   {r['case']:20s} {'FIXED' if r['fixed'] else 'not fixed':10s} {' -> '.join(r['history'])}")


if __name__ == "__main__":
    main()

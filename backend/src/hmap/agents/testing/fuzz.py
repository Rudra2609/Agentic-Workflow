"""Fuzzing (Sprint 8 stretch; research §1: property-based testing finds edge cases a model would not think of).

Targets: public top-level functions of the code under test whose parameters (at most 3) are all annotated with simple
types (``str``, ``bytes``, ``int``, ``float``, ``bool``, ``list[str]``, ``list[int]``) and whose name does not suggest
side effects (``main``, ``serve``, ``run``, ``start``, ``connect``, ``listen``, ``send``…). Each one is called with
Hypothesis-generated inputs (``derandomize=True``: the same inputs every run, so results replay), every call with a
2 s alarm. Exceptions the module defines itself, ``ValueError`` and ``TypeError`` count as "rejected the input" (a
correct answer to bad input); anything else (``IndexError``, ``ZeroDivisionError``, ``RecursionError``, a hang…) is a
**finding**, reported with Hypothesis' smallest failing input.

Findings are shown as CRASH / TIMEOUT failures labelled ``fuzz``. They do not fail the run and never start a revision
on their own: whether an empty string may raise ``IndexError`` is a requirement question, not a test verdict. Docker
only (Hypothesis is in the sandbox image, not in the local coding venv). Off by default (``inputs.fuzz`` or
``HMAP_TESTING_FUZZ=true``).
"""

import ast
import json
from typing import Any

from hmap.agents.coding.tools.checks import module_name
from hmap.agents.testing.model import FailureRecord

RUNNER_PATH = ".hmap/fuzz_runner.py"
TARGETS_PATH = ".hmap/fuzz_targets.json"
EXAMPLES = 150
MAX_TARGETS = 10
TYPES = {"str", "bytes", "int", "float", "bool", "list[str]", "list[int]"}
SIDE_EFFECTS = ("main", "serve", "run", "start", "connect", "listen", "send", "write", "delete", "remove", "save",
                "open", "accept", "loop", "forever", "shutdown", "stop")
RUNNER = r'''import importlib, json, signal, sys, traceback
from hypothesis import HealthCheck, given, settings, strategies as st
sys.path.insert(0, ".")
STRATS = {"str": st.text(max_size=200), "bytes": st.binary(max_size=200), "int": st.integers(-10**6, 10**6),
          "float": st.floats(allow_nan=False, allow_infinity=False), "bool": st.booleans(),
          "list[str]": st.lists(st.text(max_size=20), max_size=10), "list[int]": st.lists(st.integers(), max_size=10)}
targets = json.load(open(sys.argv[1], encoding="utf-8"))
examples = int(sys.argv[2])

def alarm(signum, frame):
    raise TimeoutError("one call took more than 2 s (a hang or an endless loop)")

signal.signal(signal.SIGALRM, alarm)
out = []
for t in targets:
    row = {"module": t["module"], "func": t["func"], "finding": None}
    try:
        mod = importlib.import_module(t["module"])
        fn = getattr(mod, t["func"])
    except BaseException as exc:
        row["error"] = f"cannot import: {type(exc).__name__}"
        out.append(row)
        continue
    allowed = tuple(c for c in vars(mod).values() if isinstance(c, type) and issubclass(c, Exception)
                    and c.__module__ == mod.__name__) + (ValueError, TypeError)

    @settings(max_examples=examples, deadline=None, derandomize=True, database=None, report_multiple_bugs=False,
              suppress_health_check=list(HealthCheck))
    @given(**{k: STRATS[v] for k, v in t["params"].items()})
    def check(**kw):
        signal.setitimer(signal.ITIMER_REAL, 2.0)
        try:
            fn(**kw)
        except allowed:
            pass
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    try:
        check()
    except BaseException as exc:
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename.startswith("/work/")
                  or not f.filename.startswith("/")]
        last = frames[-1] if frames else None
        notes = [n for n in getattr(exc, "__notes__", []) if "example" in n.lower() or "(" in n]
        row["finding"] = {"exception": type(exc).__name__, "message": str(exc)[:200],
                          "example": " ".join(notes)[:300],
                          "file": last.filename.replace("/work/", "") if last else None,
                          "line": last.lineno if last else None}
    out.append(row)
print("HMAP_FUZZ " + json.dumps(out))
'''


def _annotation(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    text = ast.unparse(node).replace(" ", "").replace("List[", "list[")
    return text if text in TYPES else None


def targets(files: dict[str, str], code_files: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in sorted(code_files):
        mod = module_name(rel)
        if mod is None:
            continue
        try:
            tree = ast.parse(files[rel])
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            if any(w in node.name.lower() for w in SIDE_EFFECTS):
                continue
            a = node.args
            if a.vararg or a.kwarg or a.posonlyargs or a.kwonlyargs or not a.args or len(a.args) > 3:
                continue
            params = {arg.arg: _annotation(arg.annotation) for arg in a.args}
            if any(t is None for t in params.values()) or len(a.defaults) > 0:
                continue
            out.append({"module": mod, "func": node.name, "params": params, "file": rel, "line": node.lineno})
            if len(out) >= MAX_TARGETS:
                return out
    return out


def plan_files(tgts: list[dict[str, Any]]) -> dict[str, str]:
    return {RUNNER_PATH: RUNNER, TARGETS_PATH: json.dumps(tgts)}


def parse(output: str, tgts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[FailureRecord]]:
    line = next((ln for ln in reversed(output.splitlines()) if ln.startswith("HMAP_FUZZ ")), None)
    if line is None:
        return {"targets": len(tgts), "error": "the fuzz run gave no result"}, []
    rows = json.loads(line[len("HMAP_FUZZ "):])
    where = {(t["module"], t["func"]): t for t in tgts}
    failures = []
    for r in rows:
        f = r.get("finding")
        if not f:
            continue
        t = where.get((r["module"], r["func"]), {})
        timeout = f["exception"] == "TimeoutError"
        rec = FailureRecord(
            stage="unit", category="TIMEOUT" if timeout else "CRASH", file=f.get("file") or t.get("file"),
            line=f.get("line") or t.get("line"), test=f"fuzz::{r['module']}.{r['func']}", fuzz=True,
            message=" ".join(f"fuzzing {r['func']}() found an input that "
                             f"{'hangs' if timeout else 'raises ' + f['exception']}: {f['message']} "
                             f"{f['example']}".split())[:600])
        rec.hint = (f"decide what {r['func']}() should do with this input: reject it with a ValueError (or the "
                    f"module's own error) or handle it; then add a test for it")
        failures.append(rec)
    summary = {"targets": len(tgts), "functions": [f"{t['module']}.{t['func']}" for t in tgts],
               "examples_per_function": EXAMPLES, "findings": len(failures),
               "errors": [r for r in rows if r.get("error")]}
    return summary, failures

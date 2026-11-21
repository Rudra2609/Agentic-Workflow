"""JavaScript / TypeScript projects (Sprint 8 stretch: JS/TS + per-language images).

A workspace with no Python files and a ``package.json`` or ``.js`` / ``.mjs`` / ``.cjs`` / ``.ts`` files runs in the
Node image (``hmap-sandbox-node:1``, ``make sandbox-image``: Node 22, ESLint 9 with the recommended rules,
TypeScript), with the same container limits as Python. Stages:

- **static**: ESLint (recommended rules, Node + browser globals) on JS files; ``tsc`` type errors on TS files (LINT);
- **build**: ``node --check`` on every JS file; ``tsc`` syntax errors (TS1xxx) on TS files;
- **unit**: Node's built-in test runner (``node --test``, JUnit report) on ``*.test.*``, ``*.spec.*`` and ``test/``
  files; TS tests run with ``--experimental-strip-types``. Jest / Mocha suites are not supported (nothing is
  installed at test time, there is no network);
- **security**: built-in rules (``eval``, ``new Function``, ``child_process`` with built commands, ``innerHTML``,
  ``document.write``, hard-coded secrets).

Integration and execution are not separate for JS: integration-style tests run in ``unit``. The local runner cannot
run Node (its allow-list is Python only): without Docker a JS project gets an ENV failure saying so.
"""

import json
import re

from hmap.agents.testing import analyze
from hmap.agents.testing.model import Category, FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step
from hmap.agents.testing.stages import View
from hmap.agents.testing.stages.security import SECRET_PATTERNS
from hmap.agents.testing.stages.unit import evaluate_tests

JS = (".js", ".mjs", ".cjs")
TS = (".ts", ".mts", ".cts")
_TSC = re.compile(r"^([^(\n]+)\((\d+),(\d+)\): error (TS\d+): (.*)$", re.M)
JS_RULES = [
    (re.compile(r"\beval\s*\("), "HMAP-J1 eval(): code injection when the text comes from outside", "eval"),
    (re.compile(r"\bnew\s+Function\s*\("), "HMAP-J2 new Function(): builds code from text", "eval"),
    (re.compile(r"\b(exec|execSync)\s*\(\s*(`[^`]*\$\{|[^'\"`)][^)]*\+)"),
     "HMAP-J3 child_process exec() with a built command (shell injection)", "shell"),
    (re.compile(r"\.innerHTML\s*=(?!=)"), "HMAP-J4 innerHTML set from code (cross-site scripting)", "xss"),
    (re.compile(r"\bdocument\.write\s*\("), "HMAP-J5 document.write() (cross-site scripting)", "xss"),
]


def is_js_project(files: dict[str, str]) -> bool:
    if any(f.endswith(".py") for f in files):
        return False
    return "package.json" in files or any(f.endswith(JS + TS) for f in files)


def _skipped(rel: str) -> bool:
    return rel.startswith(("node_modules/", ".hmap/")) or "/node_modules/" in rel or rel.endswith(".d.ts")


def js_files(view: View) -> list[str]:
    return sorted(f for f in view.files if f.endswith(JS) and not _skipped(f))


def ts_files(view: View) -> list[str]:
    return sorted(f for f in view.files if f.endswith(TS) and not _skipped(f))


def is_test(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(t in name for t in (".test.", ".spec.")) or name.startswith("test") or rel.startswith(("test/",
                                                                                                       "tests/"))


def steps(view: View) -> list[Step]:
    t = min(60.0, view.stage_timeout)
    js, ts = js_files(view), ts_files(view)
    out: list[Step] = []
    if js:
        out.append(Step(stage="static", name="eslint", kind="eslint", args=js[:300], timeout=t))
        out.append(Step(stage="build", name="compile", kind="node_check", args=js[:300], timeout=t))
    if ts:
        out.append(Step(stage="build", name="tsc", kind="tsc", args=ts[:300], timeout=t))
    tests = [f for f in js + ts if is_test(f)]
    if tests:
        needs = ["compile"] if js else []
        out.append(Step(stage="unit", name="unit", kind="node_test", args=tests[:200], timeout=view.stage_timeout,
                        needs=needs))
    return out


def _env(res_name: str, run: RunResult) -> str | None:
    res = run.get(res_name)
    return res.unavailable if res is not None and res.unavailable else None


def parse_eslint(report: str) -> list[FailureRecord]:
    """ESLint's JSON report (``--format json``; the plain formats left ESLint core in v9)."""
    try:
        data = json.loads(report)
    except ValueError:
        return []
    out = []
    for file_report in data if isinstance(data, list) else []:
        path = str(file_report.get("filePath", "")).removeprefix("/work/")
        for msg in file_report.get("messages", []):
            rule = msg.get("ruleId") or ""
            text = str(msg.get("message", ""))
            cat: Category = "SYNTAX" if msg.get("fatal") or "Parsing error" in text else "LINT"
            f = FailureRecord(stage="static", category=cat, file=path, line=msg.get("line") or None,
                              message=f"{rule} {text}".strip()[:300])
            f.hint = analyze.rule_hint(f) if cat == "SYNTAX" else f"fix the ESLint finding ({rule or 'eslint'})"
            out.append(f)
    return out


def parse_tsc(output: str) -> tuple[list[FailureRecord], list[FailureRecord]]:
    """(syntax errors for build, type errors for static)."""
    syntax: list[FailureRecord] = []
    types: list[FailureRecord] = []
    for m in _TSC.finditer(output):
        path, line, code, msg = m.group(1).removeprefix("/work/"), int(m.group(2)), m.group(4), m.group(5)
        is_syntax = code.startswith("TS1")
        f = FailureRecord(stage="build" if is_syntax else "static", category="SYNTAX" if is_syntax else "LINT",
                          file=path, line=line, message=f"{code} {msg}"[:300])
        f.hint = analyze.rule_hint(f) if is_syntax else "a TypeScript type error: the value does not match its type"
        (syntax if is_syntax else types).append(f)
    return syntax, types


def scan_js(rel: str, text: str) -> list[FailureRecord]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "/*")):
            continue
        for pattern, msg, key in JS_RULES:
            if pattern.search(line):
                f = FailureRecord(stage="security", category="SECURITY", file=rel, line=i, message=msg)
                f.hint = analyze.SECURITY_HINTS.get(key) or ("never put text from outside into HTML: use "
                                                            "textContent or escape it")
                out.append(f)
        for pattern, what in SECRET_PATTERNS:
            if pattern.search(line):
                f = FailureRecord(stage="security", category="SECURITY", file=rel, line=i,
                                  message=f"HMAP-S1 hard-coded secret: {what} in the code")
                f.hint = analyze.SECURITY_HINTS["secret"]
                out.append(f)
    return out


def evaluate(view: View, run: RunResult) -> dict[str, tuple[StageRecord, list[FailureRecord]]]:
    out: dict[str, tuple[StageRecord, list[FailureRecord]]] = {}
    missing = next((m for n in ("eslint", "compile", "tsc", "unit") if (m := _env(n, run))), None)
    if missing:
        f = FailureRecord(stage="build", category="ENV", message=missing[:300])
        f.hint = "start Docker (make sandbox-image once): JS/TS projects run only in the Node sandbox image"
        for name in ("static", "build", "unit", "integration", "security", "execution"):
            out[name] = (StageRecord(name=name, status="error" if name in ("static", "build", "unit") else "skipped",
                                     detail=missing[:200]), [f] if name == "build" else [])
        return out
    static_f: list[FailureRecord] = []
    build_f: list[FailureRecord] = []
    eslint, compile_, tsc = run.get("eslint"), run.get("compile"), run.get("tsc")
    if eslint is not None and not eslint.skipped:
        found = parse_eslint(eslint.files.get(".json", ""))
        build_f += [f for f in found if f.category == "SYNTAX"]
        static_f += [f for f in found if f.category != "SYNTAX"]
    if tsc is not None and not tsc.skipped:
        syn, typ = parse_tsc(tsc.output)
        build_f += syn
        static_f += typ
    if compile_ is not None and not compile_.ok and not compile_.skipped:
        frames = re.findall(r"(?:/work/)?([^\s:]+\.(?:js|mjs|cjs)):(\d+)", compile_.output)
        f = FailureRecord(stage="build", category="SYNTAX", file=frames[0][0] if frames else None,
                          line=int(frames[0][1]) if frames else None,
                          message=next((ln.strip() for ln in compile_.output.splitlines() if "SyntaxError" in ln),
                                       "node --check failed")[:300])
        f.hint = analyze.rule_hint(f)
        if not any(b.file == f.file and b.line == f.line for b in build_f):
            build_f.append(f)
    out["static"] = (StageRecord(name="static", status="failed" if static_f else ("passed" if eslint or tsc
                                                                                   else "skipped"),
                                 duration_s=sum(r.seconds for r in (eslint, tsc) if r),
                                 detail="eslint (recommended) + tsc"), static_f)
    out["build"] = (StageRecord(name="build", status="failed" if build_f else ("passed" if compile_ or tsc
                                                                                else "skipped"),
                                duration_s=compile_.seconds if compile_ else 0.0,
                                detail=f"{len(js_files(view))} JS, {len(ts_files(view))} TS files"), build_f)
    out["unit"] = evaluate_tests(view, run, "unit")
    sec: list[FailureRecord] = []
    for rel in js_files(view) + ts_files(view):
        if not is_test(rel):
            sec += scan_js(rel, view.files[rel])
    out["security"] = (StageRecord(name="security", status="failed" if sec else "passed",
                                   detail="built-in rules (eval, shell, XSS, secrets); no npm audit offline"), sec)
    out["integration"] = (StageRecord(name="integration", status="skipped", detail="JS: runs with the unit tests"), [])
    out["execution"] = (StageRecord(name="execution", status="skipped", detail="not for JS projects"), [])
    return out

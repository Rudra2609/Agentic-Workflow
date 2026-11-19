"""Debug helpers (Sprint 7 item 7.7, plan D11): turn check output into located failures, score a round, and write
the Reflexion note carried into the next round.

Parsers are rules only (no model): Python tracebacks (the innermost frame inside the workspace), unittest
``FAIL:``/``ERROR:`` blocks, pytest ``file.py:12: Error`` lines, ruff ``file.py:1:11: F401 …``, ``py_compile``
syntax errors, and Member 8's ``TestReport.failures`` (``code.revise``).
"""

import re
from dataclasses import dataclass
from typing import Any

from hmap.agents.coding.model import Check

FRAME = re.compile(r'^\s*File "(?P<file>[^"<>]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?', re.M)
EXC = re.compile(r"^(?P<exc>(?:[A-Za-z_][\w.]*)?(?:Error|Exception|Exit|Interrupt|Warning|Timeout|Failure))"
                 r"(?::\s*(?P<msg>.*))?$", re.M)
UNITTEST_HEAD = re.compile(r"^(?P<kind>FAIL|ERROR): (?P<test>\S+) \((?P<where>[^)]+)\)", re.M)
PYTEST_LOC = re.compile(r"^(?P<file>[\w./-]+\.py):(?P<line>\d+): (?P<msg>\w+.*)$", re.M)
RUFF = re.compile(r"^(?P<file>[\w./-]+\.py):(?P<line>\d+):\d+: (?P<code>[A-Z]+\d+) (?P<msg>.*)$", re.M)
RAN = re.compile(r"Ran (\d+) tests?")
UNITTEST_FAILED = re.compile(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?")
PYTEST_SUMMARY = re.compile(r"(\d+) (failed|passed|error|errors)")


@dataclass(frozen=True)
class Failure:
    kind: str                 # SYNTAX | IMPORT | ASSERTION | ERROR | LINT | TIMEOUT | TEST
    message: str
    file: str | None = None
    line: int | None = None

    def short(self) -> str:
        where = f"{self.file}:{self.line}" if self.file and self.line else (self.file or "")
        return f"[{self.kind}] {where} {self.message}".strip()[:300]


def _kind(exc: str) -> str:
    if "SyntaxError" in exc or "IndentationError" in exc:
        return "SYNTAX"
    if "ImportError" in exc or "ModuleNotFoundError" in exc:
        return "IMPORT"
    if "AssertionError" in exc:
        return "ASSERTION"
    if "Timeout" in exc:
        return "TIMEOUT"
    return "ERROR"


def _in_workspace(path: str) -> bool:
    return not path.startswith(("/", "<")) and "site-packages" not in path and "lib/python3" not in path


def parse_traceback(text: str) -> list[Failure]:
    """One failure per traceback block (the innermost workspace frame + the exception line)."""
    out: list[Failure] = []
    for block in re.split(r"(?=^Traceback \(most recent call last\):)|(?=^={20,})", text, flags=re.M):
        frames = [m for m in FRAME.finditer(block) if _in_workspace(m["file"])]
        exc = None
        for m in EXC.finditer(block):
            exc = m
        if not frames and exc is None:
            continue
        if exc is None:
            continue
        frame = frames[-1] if frames else None
        msg = f"{exc['exc']}: {exc['msg'] or ''}".strip().rstrip(":")
        out.append(Failure(_kind(exc["exc"]), msg[:300], frame["file"] if frame else None,
                           int(frame["line"]) if frame else None))
    return out


def parse_output(cmd: str, output: str, timed_out: bool = False) -> list[Failure]:
    if timed_out:
        return [Failure("TIMEOUT", f"`{cmd}` did not finish in time (an endless loop, a blocking call, or a server "
                                   "that never returns?)")]
    found: list[Failure] = []
    if cmd.startswith("ruff"):
        for m in RUFF.finditer(output):
            found.append(Failure("LINT", f"{m['code']} {m['msg']}"[:300], m["file"], int(m["line"])))
        return found
    found.extend(parse_traceback(output))
    if not found:
        for m in PYTEST_LOC.finditer(output):
            found.append(Failure(_kind(m["msg"]), m["msg"][:300], m["file"], int(m["line"])))
    if not found:
        for m in UNITTEST_HEAD.finditer(output):
            found.append(Failure("TEST", f"{m['kind']}: {m['test']} ({m['where']})"))
    if not found and output.strip():
        last = [line for line in output.strip().splitlines() if line.strip()][-3:]
        found.append(Failure("ERROR", " | ".join(last)[:300]))
    seen: set[tuple[str | None, int | None, str]] = set()
    unique = []
    for f in found:
        key = (f.file, f.line, f.message)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique[:8]


def from_test_report(failures: list[dict[str, Any]]) -> list[Failure]:
    """Member 8's ``TestReport.failures`` (category, file, line, message, hint) as :class:`Failure`."""
    out = []
    for f in failures:
        msg = str(f.get("message") or "")
        if f.get("hint"):
            msg += f" (hint: {f['hint']})"
        out.append(Failure(str(f.get("category") or "TEST"), msg[:300], f.get("file"), f.get("line")))
    return out


def score(checks: list[Check]) -> float:
    """0..1 progress of one round: compile 0.25, imports 0.15, lint 0.1, tests 0.5 (by passed fraction)."""
    weights = {"compile": 0.25, "imports": 0.15, "lint": 0.10, "tests": 0.50}
    total = got = 0.0
    for c in checks:
        w = weights.get(c.name, 0.0)
        if c.status == "skipped":
            continue
        total += w
        if c.status == "passed":
            got += w
        elif c.name == "tests":
            got += w * passed_fraction(c.detail)
    return round(got / total, 4) if total else 0.0


def passed_fraction(text: str) -> float:
    ran = RAN.search(text)
    if ran:
        n = int(ran.group(1))
        m = UNITTEST_FAILED.search(text)
        bad = (int(m.group(1) or 0) + int(m.group(2) or 0)) if m else 0
        return max(0.0, (n - bad) / n) if n else 0.0
    counts = {k: int(v) for v, k in PYTEST_SUMMARY.findall(text)}
    passed = counts.get("passed", 0)
    bad = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    return passed / (passed + bad) if passed + bad else 0.0



def reflection(round_no: int, failures: list[Failure], changed: list[str], previous: list[Failure]) -> str:
    """Rule-made Reflexion note: what is still failing and what to try differently."""
    now = {f.short() for f in failures}
    before = {f.short() for f in previous}
    same = now & before
    head = failures[0].short() if failures else "checks still failing"
    if same:
        return (f"Round {round_no}: the edit to {', '.join(changed) or 'no file'} did not fix {head}. Look at the "
                f"failing line again and try a different fix (re-read the code it calls).")
    return f"Round {round_no}: now failing: {head}. The previous problem changed, so the last edit had an effect."

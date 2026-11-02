"""The agent's own checks (plan D12): compile, lint (errors only), the workspace's existing tests, and an import
smoke test of the changed modules. Hidden benchmark tests are never visible here; generated test suites are
Member 8's job (item 8.7).
"""

import asyncio
import hashlib
from dataclasses import dataclass, field

from hmap.agents.coding.model import Check, CommandRecord
from hmap.agents.coding.tools.runner import Runner, RunResult

IMPORT_SCRIPT = '''import importlib, sys, traceback
sys.path.insert(0, ".")
bad = 0
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except SystemExit:
        pass
    except BaseException:
        bad += 1
        print(f"import {name} failed:")
        traceback.print_exc(limit=3)
sys.exit(1 if bad else 0)
'''


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel}")


def module_name(rel: str) -> str | None:
    if not rel.endswith(".py") or is_test_file(rel):
        return None
    parts = rel[:-3].split("/")
    if parts[-1] in ("__main__", "setup", "conftest"):
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    return ".".join(parts)


@dataclass
class CheckRun:
    checks: list[Check] = field(default_factory=list)
    results: list[RunResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "failed" for c in self.checks)

    def failures_for_model(self, cap: int = 6000) -> str:
        """Output of the failing commands, newest-first priority, capped (fed to the debugger)."""
        parts = [r.for_model(cap // max(1, len(self.failed_results()))) for r in self.failed_results()]
        return "\n\n".join(parts)[:cap]

    def failed_results(self) -> list[RunResult]:
        return [r for r in self.results if not r.ok]


# Identical workspace content + the same check request -> the same result: parallel parts that start from an
# unchanged project head (and every step in fake / offline mode) reuse the first run instead of starting pytest again.
_RESULTS: dict[str, CheckRun] = {}
_RESULTS_MAX = 256


class Checker:
    def __init__(self, runner: Runner, *, cancelled: asyncio.Event | None = None) -> None:
        self.runner = runner
        self.cancelled = cancelled
        self._has_pytest: bool | None = None
        self.records: list[CommandRecord] = []
        self.reused = 0

    def _key(self, changed: list[str] | None, tests: bool) -> str:
        h = hashlib.sha256()
        for rel, text in sorted(self.runner.ws.snapshot().items()):
            h.update(rel.encode() + b"\0" + text.encode() + b"\0")
        h.update(repr((self.runner.python, self.runner.settings.coding_sandbox, sorted(changed or []) if changed
                       is not None else None, tests)).encode())
        return h.hexdigest()

    async def _run(self, cmd: list[str], step: int, timeout: float | None = None) -> RunResult:
        res = await self.runner.run(cmd, timeout=timeout, cancelled=self.cancelled)
        self.records.append(CommandRecord(step=step, cmd=res.cmd, exit_code=res.exit_code, timed_out=res.timed_out,
                                          duration_s=res.duration_s, output=res.output[-8000:], denied=res.denied))
        return res

    async def has_pytest(self, step: int) -> bool:
        if self._has_pytest is None:
            script = self.runner.ws.write_tool_file("hmap_has_pytest.py", "import pytest\n")
            res = await self.runner.run(["python", script], timeout=15, cancelled=self.cancelled)
            self._has_pytest = res.ok
        return self._has_pytest

    async def run(self, step: int, changed: list[str] | None = None, *, tests: bool = True) -> CheckRun:
        key = self._key(changed, tests)
        if key in _RESULTS:
            self.reused += 1
            return _RESULTS[key]
        out = await self._run_all(step, changed, tests=tests)
        if len(_RESULTS) >= _RESULTS_MAX:
            _RESULTS.clear()
        _RESULTS[key] = out
        return out

    async def _run_all(self, step: int, changed: list[str] | None, *, tests: bool) -> CheckRun:
        ws = self.runner.ws
        out = CheckRun()
        py_files = ws.files(".py")
        targets = [f for f in (changed if changed is not None else py_files) if f.endswith(".py") and f in py_files]
        if not py_files:
            out.checks.append(Check(name="compile", status="skipped", detail="no Python files"))
            return out
        res = await self._run(["python", "-m", "py_compile", *(targets or py_files)[:200]], step)
        out.results.append(res)
        out.checks.append(Check(name="compile", status="passed" if res.ok else "failed", detail=res.output[-500:]))
        if not res.ok:
            return out
        if self.runner.ruff:
            res = await self._run(["ruff", "check", *(targets or ["."])], step)
            out.results.append(res)
            out.checks.append(Check(name="lint", status="passed" if res.ok else "failed", detail=res.output[-500:]))
        modules = sorted({m for f in (targets or py_files) if (m := module_name(f))})
        if modules:
            script = ws.write_tool_file("hmap_import_check.py", IMPORT_SCRIPT)   # .tmp/ is never packed
            res = await self._run(["python", script, *modules[:40]], step, timeout=15)
            out.results.append(res)
            out.checks.append(Check(name="imports", status="passed" if res.ok else "failed",
                                    detail=res.output[-500:]))
        test_files = [f for f in py_files if is_test_file(f)]
        if tests and test_files:
            if await self.has_pytest(step):
                cmd = ["python", "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:randomly"]
            else:
                cmd = ["python", "-m", "unittest", "discover", "-s", ".", "-p", "*test*.py"]
            res = await self._run(cmd, step)
            if res.exit_code == 5 and "pytest" in cmd:      # pytest: no tests collected
                out.checks.append(Check(name="tests", status="skipped", detail="no tests collected"))
            else:
                out.results.append(res)
                out.checks.append(Check(name="tests", status="passed" if res.ok else "failed",
                                        detail=res.output[-800:]))
        elif tests:
            out.checks.append(Check(name="tests", status="skipped", detail="the workspace has no tests"))
        return out

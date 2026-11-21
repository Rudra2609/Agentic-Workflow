"""Local fallback sandbox (plan D2): Member 7's jailed runner when Docker is not running.

The workspace is written to a fresh folder outside the project (``HMAP_CODING_WORK_DIR``), every command goes
through :class:`hmap.agents.coding.tools.runner.Runner`: allow-list (python -m pytest / py_compile, a script in the
workspace, ruff errors-only), an environment rebuilt from nothing (no keys, no ``HMAP_*``), the coding interpreter
(never the backend venv), macOS ``sandbox-exec`` (no network except localhost, no reads of the project folder or
home, writes only in the workspace), per-command time limit (at most 60 s) and output cap.

Weaker than Docker: no memory / pids limits, the host kernel and file system with a deny-list. ``mypy`` and
``bandit`` are not available here (mypy can load plug-ins named in the workspace's config, i.e. run code); the
security stage still runs the built-in rules on the host (:mod:`..stages.security`), which read code only.
"""

import asyncio
import shutil
import time
import uuid

from hmap.agents.coding.tools.runner import Runner
from hmap.agents.coding.workspace import Workspace, work_root
from hmap.agents.testing.sandbox import RunResult, Step, StepResult
from hmap.core.config import Settings

NODE = "JS/TS projects run only in the Docker sandbox (the Node image)"
UNAVAILABLE = {"mypy": "mypy runs only in the Docker sandbox", "bandit": "bandit runs only in the Docker sandbox",
               "eslint": NODE, "node_check": NODE, "tsc": NODE, "node_test": NODE}
IMPORT_CHECK = '''import importlib, sys, traceback
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
        traceback.print_exc(limit=-8)
sys.exit(1 if bad else 0)
'''


class LocalBackend:
    name = "local"
    isolation = ("local jailed runner (no Docker): allow-listed commands, no keys in the environment, macOS "
                 "sandbox-exec; no memory or process limits")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _argv(self, step: Step, ws: Workspace) -> list[str] | None:
        if step.kind == "ruff":
            return ["ruff", "check", *(step.args or ["."])]
        if step.kind == "compile":
            return ["python", "-m", "py_compile", *step.args]
        if step.kind == "imports":
            return ["python", ws.write_tool_file("hmap_import_check.py", IMPORT_CHECK), *step.args]
        if step.kind == "pytest":
            return ["python", "-m", "pytest", "-q", "--tb=short", "-rfE", f"--junitxml=.tmp/{step.name}.xml",
                    *step.args]
        if step.kind == "script":
            return ["python", *step.args]
        return None

    async def run(self, files: dict[str, str], steps: list[Step], *,
                  cancelled: asyncio.Event | None = None, image: str | None = None) -> RunResult:
        from hmap.agents.testing.governor import slot

        async with slot(self.settings):
            return await self._run(files, steps, cancelled)

    async def _run(self, files: dict[str, str], steps: list[Step], cancelled: asyncio.Event | None) -> RunResult:
        folder = work_root(self.settings) / "testing" / uuid.uuid4().hex[:16]
        folder.mkdir(parents=True)
        started = time.monotonic()
        res = RunResult(backend=self.name)
        try:
            ws = Workspace(folder)
            for rel, text in files.items():
                ws.write(rel, text)
            runner = Runner(ws, self.settings)
            passed: set[str] = set()
            for step in steps:
                if any(n not in passed for n in step.needs):
                    res.steps.append(StepResult(name=step.name, stage=step.stage, skipped=True))
                    continue
                if step.kind in UNAVAILABLE:
                    res.steps.append(StepResult(name=step.name, stage=step.stage, unavailable=UNAVAILABLE[step.kind]))
                    continue
                argv = self._argv(step, ws)
                if argv is None:
                    res.steps.append(StepResult(name=step.name, stage=step.stage, unavailable=f"{step.kind}?"))
                    continue
                run = await runner.run(argv, timeout=step.timeout, cancelled=cancelled)
                out = StepResult(name=step.name, stage=step.stage, cmd=run.cmd, exit_code=run.exit_code,
                                 timed_out=run.timed_out, output=run.output if not run.denied else
                                 f"DENIED: {run.denied}", seconds=run.duration_s)
                if run.denied:
                    out.unavailable = run.denied
                junit = folder / ".tmp" / f"{step.name}.xml"
                if step.kind == "pytest" and junit.is_file():
                    out.files[".xml"] = junit.read_text(encoding="utf-8", errors="replace")[:200_000]
                if out.ok:
                    passed.add(step.name)
                res.steps.append(out)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        res.seconds = round(time.monotonic() - started, 3)
        return res



"""Code-example / command verifier (Sprint 9 item 9.7, plan D8): documented snippets run in Member 8's sandbox.

Each fenced ``python`` block and each command line of a ``bash`` block gets one action:

- **run** (in the sandbox, no network, one container for all of them): Python snippets; ``python x.py --help``;
  ``python x.py ...`` for a script that does not serve or listen; ``pytest`` / ``python -m pytest``.
- **check** (never run, matched against the facts by the grounding rules): installs (``pip``, ``uv``, ``npm``),
  ``docker``, ``make``, ``curl`` to local routes, servers (``uvicorn``, scripts that listen).
- **skip** with the reason: everything else (``rm``, ``sudo``, network tools, shell built-ins).

A snippet that fails because a declared dependency is missing in the sandbox image is reported as skipped (not
the document's fault). A real failure is an issue for the refine loop (``refine_hook``).
"""

import re
import shlex
from typing import Any

from hmap.agents.docgen.grounding.rules import FENCE, joined_lines
from hmap.agents.docgen.model import ExampleResult, Facts
from hmap.agents.docgen.readme import long_running
from hmap.core.tracing import get_logger

log = get_logger("hmap.docgen.examples")

MAX_EXAMPLES = 12
TIMEOUT_S = 20.0
CHECK_TOOLS = {"pip", "pip3", "uv", "npm", "npx", "pnpm", "yarn", "docker", "docker-compose", "make", "curl",
               "uvicorn", "cd", "git", "export", "source", "colima", "ollama", "brew"}
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")


def collect(docs: dict[str, str]) -> list[ExampleResult]:
    out: list[ExampleResult] = []
    for name, md in docs.items():
        for m in FENCE.finditer(md):
            lang, block = m.group(1).lower(), m.group(2)
            line = md.count("\n", 0, m.start()) + 2
            if lang in ("python", "py", "python3"):
                out.append(ExampleResult(doc=name, line=line, language="python", code=block, action="run"))
            elif lang in ("bash", "sh", "shell", "console", "zsh"):
                for i, cmd in joined_lines(block):
                    cmd = re.sub(r"^\$\s*", "", cmd.strip())
                    if cmd and not cmd.startswith("#"):
                        out.append(ExampleResult(doc=name, line=line + i, language="bash", code=cmd, action="skip"))
    return out


def classify(ex: ExampleResult, facts: Facts) -> ExampleResult:
    if ex.language == "python":
        ex.action, ex.why = "run", "Python snippet"
        return ex
    try:
        argv = shlex.split(ex.code, comments=True)
    except ValueError:
        ex.action, ex.why = "skip", "cannot be parsed"
        return ex
    while argv and re.fullmatch(r"[A-Z_][A-Z0-9_]*=\S*", argv[0]):
        argv.pop(0)
    if not argv:
        ex.action, ex.why = "skip", "only environment settings"
        return ex
    tool, args = argv[0], argv[1:]
    if (tool in ("python", "python3") and args[:2] == ["-m", "pytest"]) or tool == "pytest":
        ex.action, ex.why = "run", "test command"
    elif tool in ("python", "python3") and args[:1] == ["-m"]:
        ex.action, ex.why = "check", "runs an installed module: checked against the facts, not run"
    elif tool in ("python", "python3") and args and args[0].endswith(".py"):
        script = args[0].removeprefix("./")
        if "--help" in args or "-h" in args:
            ex.action, ex.why = "run", "help of a script"
        elif long_running(facts, script):
            ex.action, ex.why = "check", "long-running (a server or network client): checked against the facts, not run"
        elif (m := facts.modules.get(script)) is not None and "." in m.module:
            ex.action, ex.why = "check", "a module inside a package: it needs the project installed, so it is not run"
        elif any(a == "VALUE" for a in args):
            ex.action, ex.why = "check", "needs a value the reader fills in"
        else:
            ex.action, ex.why = "run", "script"
    elif tool in CHECK_TOOLS or tool.endswith(".sh") or tool.startswith(("scripts/", "./")):
        ex.action, ex.why = "check", "install / infrastructure command: checked against the facts, not run"
    else:
        ex.action, ex.why = "skip", f"{tool} is not run by the verifier"
    return ex


def _argv(ex: ExampleResult) -> list[str]:
    argv = shlex.split(ex.code, comments=True)
    while argv and re.fullmatch(r"[A-Z_][A-Z0-9_]*=\S*", argv[0]):
        argv.pop(0)
    return argv


async def verify(docs: dict[str, str], facts: Facts, files: dict[str, str], backend: Any) -> list[ExampleResult]:
    """Classify every snippet and run the runnable ones (one sandbox call). ``backend=None`` -> nothing runs."""
    from hmap.agents.testing.sandbox import Step

    found = [classify(e, facts) for e in collect(docs)]
    unique: dict[tuple[str, str], ExampleResult] = {}
    for e in found:                                  # the same command in the README and the report runs once
        if e.action == "run":
            unique.setdefault((e.language, e.code.strip()), e)
    runnable = list(unique.values())[:MAX_EXAMPLES]
    for e in found:
        if e.action == "run" and e not in runnable and unique.get((e.language, e.code.strip())) not in runnable:
            e.action, e.why = "skip", f"more than {MAX_EXAMPLES} runnable examples"
    if backend is None or not runnable:
        for e in runnable:
            e.action, e.why = "skip", "no sandbox available"
        return found
    extra: dict[str, str] = {}
    steps = []
    for n, e in enumerate(runnable, 1):
        if e.language == "python":
            path = f"docgen_example_{n}.py"          # at the root: the snippet imports the project's modules
            extra[path] = e.code
            steps.append(Step(stage="execution", name=f"ex{n}", kind="script", args=[path], timeout=TIMEOUT_S))
        else:
            argv = _argv(e)
            if argv[0] == "pytest" or argv[1:3] == ["-m", "pytest"]:
                rest = argv[1:] if argv[0] == "pytest" else argv[3:]
                steps.append(Step(stage="execution", name=f"ex{n}", kind="pytest", args=rest, timeout=TIMEOUT_S * 3))
            else:
                steps.append(Step(stage="execution", name=f"ex{n}", kind="script", args=argv[1:], timeout=TIMEOUT_S))
    try:
        run = await backend.run({**files, **extra}, steps)
    except Exception as exc:
        for e in runnable:
            e.action, e.ok, e.why = "skip", None, f"the sandbox failed: {type(exc).__name__}"
        return found
    deps = {d.replace("-", "_") for d in facts.dependencies}
    own = {m.module.split(".")[0] for m in facts.modules.values() if "." in m.module}
    for n, e in enumerate(runnable, 1):
        e.backend = run.backend
        res = run.get(f"ex{n}")
        if res is None or res.unavailable:
            e.action, e.why = "skip", (res.unavailable if res else run.error) or "not run"
            continue
        e.output = res.output[-1500:]
        missing = MISSING_MODULE.search(res.output)
        if res.ok:
            e.ok, e.why = True, f"ran in the {run.backend} sandbox ({res.seconds:.1f} s)"
        elif missing and (missing.group(1).split(".")[0].lower() in deps or missing.group(1).split(".")[0] in own):
            e.action, e.ok = "skip", None
            e.why = f"needs {missing.group(1)} installed (a dependency or the project itself); the sandbox has not"
        elif res.timed_out:
            e.ok, e.why = False, f"did not finish within {steps[n - 1].timeout:.0f} s"
        else:
            last = next((x for x in reversed(res.output.strip().splitlines()) if x.strip()), "")
            e.ok, e.why = False, f"exit code {res.exit_code}: {last[:200]}"
    for e in found:
        first = unique.get((e.language, e.code.strip()))
        if first is not None and first is not e and e.action == "run":
            e.action, e.ok, e.why, e.output, e.backend = first.action, first.ok, first.why, first.output, first.backend
    return found

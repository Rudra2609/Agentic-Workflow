"""Allow-listed command runner (Sprint 7 item 7.4, plan D5; ported from ``samples/coding/workspace.py``).

Commands are argv lists (no shell). Allowed, after every path argument passes the workspace jail:

- ``python -m unittest …``, ``python -m pytest …`` (also ``pytest …``), ``python -m py_compile <files>``,
  ``python <script in the workspace> …`` — run with the coding interpreter (:mod:`.sandbox`), flags ``-E -s -B
  -X utf8`` (no ``PYTHON*`` variables, no user site, no bytecode);
- ``ruff check [paths]`` — the backend's ruff with ``--isolated --select E9,F`` (errors only, not style).

Everything else (``sh``, ``rm``, ``curl``, ``python -c``, ``-m http.server``, ``pip install``, a script outside the
workspace, …) is refused and audited. The environment is rebuilt from nothing (no API keys, no ``HMAP_*``), there is
a time limit, the process group is killed on timeout / cancel / output flood, and the output the model sees is
capped and normalised (workspace path → ``<ws>``, timings and addresses removed: replay-stable, plan D19).
"""

import asyncio
import contextlib
import os
import re
import shlex
import signal
import time
from collections.abc import Sequence
from dataclasses import dataclass

from hmap.agents.coding.tools import sandbox
from hmap.agents.coding.workspace import JailError, Workspace
from hmap.core.config import Settings
from hmap.core.errors import Cancelled

MODEL_OUTPUT_CAP = 10_000        # what the model sees
TRACE_OUTPUT_CAP = 64_000        # what the trace keeps
FLOOD_BYTES = 2_000_000          # kill a process that prints more than this
PY_FLAGS = ("-E", "-s", "-B", "-X", "utf8")
DENIED_MODULES_HINT = "allowed: python -m unittest | python -m pytest | python -m py_compile <files> | " \
                      "python <script.py in the workspace> | ruff check [paths]"


@dataclass
class RunResult:
    cmd: str
    exit_code: int | None = None
    output: str = ""
    timed_out: bool = False
    truncated: bool = False
    duration_s: float = 0.0
    denied: str | None = None

    @property
    def ok(self) -> bool:
        return self.denied is None and not self.timed_out and self.exit_code == 0

    def for_model(self, cap: int = MODEL_OUTPUT_CAP) -> str:
        if self.denied:
            return f"$ {self.cmd}\nDENIED: {self.denied}"
        status = "TIMED OUT (killed)" if self.timed_out else f"exit code {self.exit_code}"
        out = self.output
        if len(out) > cap:
            out = out[: cap // 2] + "\n…[output cut]…\n" + out[-cap // 2:]
        return f"$ {self.cmd}\n{out.rstrip()}\n[{status}]"


_TIMING = [
    (re.compile(r"""(["'\s])/[^"'\s]*?(/lib/python3\.\d+/)"""), r"\1<python>\2"),   # stdlib / site-packages paths
    (re.compile(r"(Ran \d+ tests?) in [\d.]+s"), r"\1"),
    (re.compile(r"(?<=\S) in \d+(?:\.\d+)?s( \([\d:]+\))?(?=\s|$)"), ""),   # pytest summary lines
    (re.compile(r"0x[0-9a-fA-F]{6,}"), "0x?"),
    (re.compile(r"\btmp[a-z0-9_]{8}\b"), "tmpXXXXXXXX"),                      # tempfile names
    (re.compile(r"pytest-of-[^/\s]+/pytest-\d+"), "pytest-of-X/pytest-N"),
    (re.compile(r"\bport \d{4,5}\b"), "port N"),
    (re.compile(r"\('127\.0\.0\.1', \d+\)"), "('127.0.0.1', N)"),
]


def normalise(text: str, ws: Workspace, extra_paths: Sequence[str] = ()) -> str:
    """Make command output replay-stable and free of local paths."""
    roots = {str(ws.root), str(ws.root).replace("/private/var/", "/var/", 1)}
    for root in sorted(roots, key=len, reverse=True):
        text = text.replace(root + "/", "").replace(root, "<ws>")
    for p in sorted(set(extra_paths), key=len, reverse=True):
        if p:
            text = text.replace(p, "<python>")
    for pattern, repl in _TIMING:
        text = pattern.sub(repl, text)
    return text


class Runner:
    def __init__(self, ws: Workspace, settings: Settings) -> None:
        self.ws = ws
        self.settings = settings
        self.python = sandbox.interpreter(settings)
        self.ruff = sandbox.ruff_binary()
        self.audit: list[str] = ws.audit
        self._py_paths = [str(p) for p in {os.path.dirname(os.path.dirname(self.python)),
                                           os.path.dirname(os.path.dirname(os.path.realpath(self.python)))}]

    # --- the allow-list ------------------------------------------------------------------------------------------
    def _arg_paths(self, args: Sequence[str]) -> None:
        for a in args:
            value = a.split("=", 1)[1] if a.startswith("-") and "=" in a else a
            if value.startswith("-") or not value:
                continue
            if value.startswith(("/", "~")) or ".." in value.split("/") or "\0" in value:
                raise self.ws.deny("command", a, "arguments must be paths inside the workspace")
            if "/" in value or value.endswith(".py"):
                self.ws.path(value)

    def plan(self, cmd: str | Sequence[str]) -> tuple[list[str], bool]:
        """(real argv, needs sandbox) for an allowed command; raises :class:`JailError` otherwise."""
        try:
            argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        except ValueError as exc:
            raise self.ws.deny("command", str(cmd), f"cannot parse ({exc})") from None
        what = " ".join(argv) or "(empty)"
        if not argv:
            raise self.ws.deny("command", what, "empty command")
        head, args = os.path.basename(argv[0]), argv[1:]
        if head == "pytest":
            head, args = "python", ["-m", "pytest", *args]
        if head == "ruff":
            if self.ruff is None:
                raise self.ws.deny("command", what, "ruff is not installed here")
            if not args or args[0] != "check":
                raise self.ws.deny("command", what, "only 'ruff check [paths]' is allowed")
            paths = [a for a in args[1:] if not a.startswith("-")] or ["."]
            self._arg_paths(paths)
            return [self.ruff, "check", "--isolated", "--no-cache", "--select", "E9,F", "--output-format",
                    "concise", *paths], False
        if head not in ("python", "python3") and not re.fullmatch(r"python3(\.\d+)?", head):
            raise self.ws.deny("command", what, f"'{head}' may not run here. {DENIED_MODULES_HINT}")
        if args[:2] == ["-m", "unittest"] or args[:2] == ["-m", "pytest"]:
            self._arg_paths(args[2:])
            extra = ["-p", "no:cacheprovider"] if args[1] == "pytest" else []
            return [self.python, *PY_FLAGS, "-m", args[1], *extra, *args[2:]], True
        if args[:2] == ["-m", "py_compile"] and len(args) > 2:
            self._arg_paths(args[2:])
            for f in args[2:]:
                self.ws.path(f)
            return [self.python, *PY_FLAGS, "-m", "py_compile", *args[2:]], True
        if args and not args[0].startswith("-") and args[0].endswith(".py"):
            self.ws.path(args[0])
            self._arg_paths(args[1:])
            return [self.python, *PY_FLAGS, *args], True
        raise self.ws.deny("command", what, f"not on the allow-list (no -c, no other modules). {DENIED_MODULES_HINT}")

    def env(self) -> dict[str, str]:
        tmp = self.ws.root / ".tmp"
        tmp.mkdir(exist_ok=True)
        return {"PATH": os.defpath, "HOME": str(self.ws.root), "TMPDIR": str(tmp), "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8"}   # nothing inherited: no keys, no tokens, no HMAP_* settings

    # --- running -------------------------------------------------------------------------------------------------
    async def run(self, cmd: str | Sequence[str], *, timeout: float | None = None,
                  cancelled: asyncio.Event | None = None) -> RunResult:
        shown = cmd if isinstance(cmd, str) else shlex.join(cmd)
        try:
            real, boxed = self.plan(cmd)
        except JailError as exc:
            return RunResult(cmd=shown, denied=str(exc).split(": ", 1)[-1])
        self.audit.append(f"command allowed: {shown}")
        if boxed:
            real = sandbox.wrap(real, self.ws.root, self.settings)
        limit = min(float(timeout or self.settings.coding_cmd_timeout_s), 60.0)
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *real, cwd=str(self.ws.root), env=self.env(), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        buf = bytearray()
        size = 0
        flooded = False

        async def pump() -> None:
            nonlocal size, flooded
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(65536):
                size += len(chunk)
                if len(buf) < TRACE_OUTPUT_CAP:
                    buf.extend(chunk[: TRACE_OUTPUT_CAP - len(buf)])
                if size > FLOOD_BYTES:
                    flooded = True
                    return

        reader = asyncio.create_task(pump())
        waiter = asyncio.create_task(proc.wait())
        stop = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        watched = {reader, waiter} | ({stop} if stop else set())
        timed_out = was_cancelled = False
        deadline = started + limit
        try:
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    timed_out = True
                    break
                done, _ = await asyncio.wait(watched, timeout=left, return_when=asyncio.FIRST_COMPLETED)
                if stop is not None and stop in done:
                    was_cancelled = True
                    break
                if reader in done and flooded:
                    break
                if waiter in done:
                    # let the reader drain what the process printed (children may keep the pipe open)
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(reader), timeout=0.5)
                    break
                if reader in done:
                    watched.discard(reader)
        finally:
            self._kill(proc.pid)
            for t in (reader, stop):
                if t is not None and not t.done():
                    t.cancel()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter, timeout=5)
            transport = getattr(proc, "_transport", None)
            if transport is not None:      # close the pipes now, not in __del__ after the loop is gone
                transport.close()
        if was_cancelled:
            raise Cancelled("execution cancelled while a command was running")
        text = normalise(buf.decode("utf-8", "replace"), self.ws, self._py_paths)
        if flooded:
            text += f"\n[killed: printed more than {FLOOD_BYTES // 1_000_000} MB]"
        return RunResult(cmd=shown, exit_code=None if (timed_out or flooded) else proc.returncode, output=text,
                         timed_out=timed_out, truncated=size > len(buf),
                         duration_s=round(time.monotonic() - started, 3))

    @staticmethod
    def _kill(pid: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)

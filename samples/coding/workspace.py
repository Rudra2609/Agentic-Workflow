#!/usr/bin/env python3
"""Path-jailed workspace + allow-listed command runner for the coding agent (Member 7, prepared ahead of Sprint 7
items 7.1 / 7.4). Plain Python 3.11.

Every file path the agent gives is resolved (following ``..`` and symlinks) and must stay inside the workspace.
Commands run with no shell, in the workspace, with a scrubbed environment (no API keys reach generated code), a
time limit and an output cap, and only if they match the allow-list. Every decision is kept in ``audit``.

This is the Sprint 7 *lightweight* boundary. Real isolation (no network, memory and process limits) is Member 8's
Docker sandbox in Sprint 8.
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


class JailError(Exception):
    """A path or command the agent is not allowed to use."""


@dataclass
class RunResult:
    argv: list[str]
    exit_code: int | None
    output: str
    timed_out: bool = False
    truncated: bool = False


@dataclass
class Workspace:
    root: Path
    audit: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, what, "allowed" | reason denied)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve(strict=True)

    # --- files ---------------------------------------------------------------------------------------------------
    def path(self, rel: str) -> Path:
        if not rel or "\0" in rel:
            raise self._deny("path", repr(rel), "empty path or NUL byte")
        if Path(rel).is_absolute():
            raise self._deny("path", rel, "absolute paths are not allowed; use a path inside the workspace")
        resolved = (self.root / rel).resolve()  # follows .. and every symlink that exists
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise self._deny("path", rel, "resolves outside the workspace (.. or a symlink)")
        return resolved

    def read(self, rel: str) -> str:
        return self.path(rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def write(self, rel: str, text: str) -> None:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path(rel)  # re-check after creating folders
        target.write_text(text, encoding="utf-8")

    def files(self, suffix: str = "") -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob(f"*{suffix}")
                      if p.is_file() and "__pycache__" not in p.parts)

    # --- commands ------------------------------------------------------------------------------------------------
    def check_command(self, argv: list[str]) -> list[str]:
        """Allowed: python3 -m unittest ..., python3 -m py_compile <files in the workspace>,
        python3 <script in the workspace> [args]. Anything else is denied."""
        what = " ".join(argv)
        if not argv or Path(argv[0]).name not in ("python", "python3"):
            raise self._deny("command", what, f"only python3 may run, not {argv[0] if argv else 'nothing'}")
        args = argv[1:]
        if args[:2] == ["-m", "unittest"]:
            return [sys.executable, *args]
        if args[:2] == ["-m", "py_compile"] and len(args) > 2:
            for f in args[2:]:
                self.path(f)
            return [sys.executable, *args]
        if args and not args[0].startswith("-") and args[0].endswith(".py"):
            self.path(args[0])
            return [sys.executable, *args]
        raise self._deny("command", what, "not on the allow-list (unittest, py_compile, or a script in the "
                                          "workspace; no -c, no other modules)")

    def run(self, argv: list[str], timeout: float = 20, max_output: int = 64_000) -> RunResult:
        real = self.check_command(argv)
        self.audit.append(("command", " ".join(argv), "allowed"))
        env = {"PATH": os.defpath, "HOME": str(self.root), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8"}  # nothing inherited: no keys, no tokens
        proc = subprocess.Popen(real, cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            out, _ = proc.communicate()
            timed_out = True
        text = out.decode("utf-8", "replace")
        return RunResult(argv, None if timed_out else proc.returncode, text[:max_output], timed_out,
                         len(text) > max_output)

    def _deny(self, kind: str, what: str, reason: str) -> JailError:
        self.audit.append((kind, what, reason))
        return JailError(f"{what}: {reason}")

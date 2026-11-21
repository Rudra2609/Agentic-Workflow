"""Where generated code runs (Sprint 8 items 8.1 / 8.11, plan D1-D4, D11).

A pipeline is a list of :class:`Step` s (what to run, in which stage, with which time limit); a backend runs the
whole list for one workspace and returns a :class:`StepResult` per step. Two backends:

- :class:`~.docker.DockerBackend`: a fresh locked-down container per run (no network, read-only, non-root, no
  capabilities, memory / CPU / pids limits, hard timeout, capped output). The agent runs on the host and calls the
  ``docker`` CLI; no container ever sees the Docker socket (plan D1).
- :class:`~.local.LocalBackend`: Member 7's jailed runner (allow-list, scrubbed environment, macOS ``sandbox-exec``,
  the coding venv) when Docker is not running. Weaker isolation, said so in the report (plan D2).

:func:`choose` picks one from ``HMAP_TESTING_SANDBOX`` (``auto`` = Docker when it answers and the image exists).
"""

import asyncio
from dataclasses import dataclass, field
from typing import Literal, Protocol

from hmap.core.config import Settings

StepKind = Literal["ruff", "mypy", "compile", "imports", "pytest", "bandit", "script", "eslint", "node_check", "tsc",
                   "node_test"]


@dataclass
class Step:
    stage: str
    name: str
    kind: StepKind
    args: list[str] = field(default_factory=list)
    timeout: float = 30.0
    needs: list[str] = field(default_factory=list)      # step names that must have passed, else skipped
    stdin: str | None = None
    coverage: bool = False

    def plan(self) -> dict[str, object]:
        return {"name": self.name, "kind": self.kind, "args": self.args, "timeout": self.timeout,
                "needs": self.needs, "stdin": self.stdin, "coverage": self.coverage}


@dataclass
class StepResult:
    name: str
    stage: str
    cmd: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    output: str = ""
    seconds: float = 0.0
    files: dict[str, str] = field(default_factory=dict)   # ".xml" (JUnit), ".cov.json", ".json" (bandit)
    skipped: bool = False
    unavailable: str | None = None                          # the backend cannot run this kind of step

    @property
    def ok(self) -> bool:
        return not self.skipped and self.unavailable is None and not self.timed_out and self.exit_code == 0


@dataclass
class RunResult:
    backend: str
    steps: list[StepResult] = field(default_factory=list)
    seconds: float = 0.0
    killed: bool = False          # the whole run hit its time limit
    oom_killed: bool = False
    error: str | None = None       # the sandbox itself failed (ENV)

    def get(self, name: str) -> StepResult | None:
        return next((s for s in self.steps if s.name == name), None)


class Backend(Protocol):
    name: str
    isolation: str

    async def run(self, files: dict[str, str], steps: list[Step], *,
                  cancelled: asyncio.Event | None = None, image: str | None = None) -> RunResult: ...


async def choose(settings: Settings) -> Backend:
    from hmap.agents.testing.sandbox.docker import DockerBackend, docker_ready
    from hmap.agents.testing.sandbox.local import LocalBackend

    if settings.testing_sandbox == "local":
        return LocalBackend(settings)
    if settings.testing_sandbox == "docker" or await docker_ready(settings.testing_image):
        return DockerBackend(settings)
    return LocalBackend(settings)

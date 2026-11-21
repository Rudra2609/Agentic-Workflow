"""Docker sandbox (Sprint 8 item 8.1, plan D1, D3, D4; ported from ``samples/testing/sandbox/run_sandbox.py``).

Every run is a fresh container with:

- ``--network none`` (only loopback: a TCP server and its clients can talk inside one run, ports are private to it);
- ``--read-only`` root filesystem; the code lives in a size-capped tmpfs ``/work``, never a host folder; ``/tmp`` is
  a small tmpfs. The workspace goes in as a tar on stdin (Colima cannot mount the external drive, and nothing on
  the host is ever exposed);
- ``--user 10001``, ``--cap-drop ALL``, ``--security-opt no-new-privileges``;
- ``--memory`` = ``--memory-swap`` (no swap escape), ``--cpus 1``, ``--pids-limit 64`` (fork bombs);
- a hard wall-clock limit (the container is killed) and at most 2 MB of output kept.

The agent calls the ``docker`` CLI from the host (plan D1): no container gets ``/var/run/docker.sock``.
"""

import asyncio
import base64
import contextlib
import io
import json
import tarfile
import time
import uuid

from hmap.agents.testing.sandbox import RunResult, Step, StepResult
from hmap.core.config import Settings
from hmap.core.errors import Cancelled
from hmap.core.tracing import get_logger

log = get_logger("hmap.testing.docker")

LABEL = "hmap.sandbox=1"
HOST_OUTPUT_CAP = 2_000_000
START_MARGIN_S = 20.0
RUN_CAP_S = 900.0
_READY: dict[str, tuple[float, bool]] = {}
READY_TTL_S = 60.0


async def _docker(*args: str, timeout: float = 30.0, stdin: bytes | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        return 127, "docker is not installed"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        return 124, f"docker {args[0]} timed out"
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def docker_ready(image: str) -> bool:
    """Docker answers and the sandbox image exists (cached for a minute; a task never builds the image)."""
    now = time.monotonic()
    hit = _READY.get(image)
    if hit and now - hit[0] < READY_TTL_S:
        return hit[1]
    code, _ = await _docker("info", "--format", "{{.ServerVersion}}", timeout=8)
    ok = code == 0 and (await _docker("image", "inspect", image, timeout=8))[0] == 0
    _READY[image] = (now, ok)
    return ok


def forget_ready() -> None:
    _READY.clear()


def tar_files(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for rel, text in sorted(files.items()):
            data = text.encode("utf-8")
            info = tarfile.TarInfo(rel)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


NPROC = 100                    # processes + threads of the sandbox user, per step (setrlimit inside)
GVISOR_AS_EXTRA_MB = 512       # gVisor: per-process address-space cap = memory + this (thread stacks are virtual)
GVISOR_EXTRA_MB = 1024         # gVisor's own kernel lives inside the container's memory cgroup: room above the cap
GVISOR_PIDS = 512              # ... and its host threads count against --pids-limit


def docker_args(settings: Settings, name: str, plan: list[dict[str, object]], image: str | None = None) -> list[str]:
    """Under runc the cgroup limits stop the program itself (the OOM killer picks the hog, ``fork`` fails at the pids
    limit) and the runner adds a process cap. Under gVisor (``--runtime runsc``) the cgroup limits bound gVisor's own
    kernel: hitting them kills the whole run. So the cgroup gets headroom and per-process limits inside
    (``setrlimit`` in stages.py: processes, address space) stop the program first."""
    gvisor = settings.testing_runtime == "runsc"
    mem = f"{settings.testing_memory_mb + (GVISOR_EXTRA_MB if gvisor else 0)}m"
    pids = str(GVISOR_PIDS if gvisor else 64)
    runtime = ["--runtime", settings.testing_runtime] if settings.testing_runtime else []
    node = bool(image and image == settings.testing_image_node)
    as_mb = settings.testing_memory_mb + GVISOR_AS_EXTRA_MB if gvisor and not node else 0   # V8 reserves huge spaces
    limits = {"nproc": NPROC, "as_mb": as_mb}
    encoded = base64.b64encode(json.dumps({"steps": plan, "limits": limits}).encode()).decode()
    return ["run", "-i", "--name", name, "--label", LABEL, "--network", "none", "--read-only",
            "--tmpfs", "/work:rw,exec,size=64m,uid=10001,gid=10001",
            "--tmpfs", "/tmp:rw,exec,size=32m,uid=10001,gid=10001",
            "--memory", mem, "--memory-swap", mem, "--cpus", "1", "--pids-limit", pids,
            "--user", "10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", *runtime,
            image or settings.testing_image, "python3", "/opt/hmap/stages.py", encoded]


async def reap(older_than_s: float = RUN_CAP_S + 60) -> int:
    """Remove sandbox containers left behind by a crashed process (exited, or running longer than any run may)."""
    code, out = await _docker("ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.ID}} {{.State}} {{.Names}}",
                              timeout=15)
    if code != 0:
        return 0
    gone = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        cid, state = parts[0], parts[1]
        if state != "running":
            gone += (await _docker("rm", "-f", cid, timeout=15))[0] == 0
            continue
        code, started = await _docker("inspect", "--format", "{{.State.StartedAt}}", cid, timeout=10)
        if code == 0 and _age_s(started.strip()) > older_than_s:
            gone += (await _docker("rm", "-f", cid, timeout=15))[0] == 0
    return gone


def _age_s(started_at: str) -> float:
    from datetime import UTC, datetime
    try:
        ts = datetime.fromisoformat(started_at[:26].rstrip("Z") + "+00:00")
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - ts).total_seconds()


class DockerBackend:
    name = "docker"
    isolation = "Docker: no network, read-only, non-root, no capabilities, memory/CPU/pids limits"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(self, files: dict[str, str], steps: list[Step], *,
                  cancelled: asyncio.Event | None = None, image: str | None = None) -> RunResult:
        from hmap.agents.testing.governor import slot

        async with slot(self.settings):
            return await self._run(files, steps, cancelled, image)

    async def _run(self, files: dict[str, str], steps: list[Step], cancelled: asyncio.Event | None,
                   image: str | None = None) -> RunResult:
        name = f"hmap-sbx-{uuid.uuid4().hex[:12]}"
        limit = min(sum(s.timeout for s in steps) + START_MARGIN_S, RUN_CAP_S)
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", *docker_args(self.settings, name, [s.plan() for s in steps], image),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        except FileNotFoundError:
            return RunResult(backend=self.name, error="docker is not installed")
        kept = bytearray()

        async def pump() -> None:
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(65536):
                room = HOST_OUTPUT_CAP - len(kept)
                if room > 0:
                    kept.extend(chunk[:room])

        async def feed() -> None:
            assert proc.stdin is not None
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.write(tar_files(files))
                await proc.stdin.drain()
                proc.stdin.close()

        reader = asyncio.create_task(pump())
        writer = asyncio.create_task(feed())
        waiter = asyncio.create_task(proc.wait())
        stop = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        killed = was_cancelled = False
        try:
            done, _ = await asyncio.wait({waiter} | ({stop} if stop else set()), timeout=limit,
                                         return_when=asyncio.FIRST_COMPLETED)
            if stop is not None and stop in done:
                was_cancelled = True
            elif waiter not in done:
                killed = True
        finally:
            if killed or was_cancelled:
                await _docker("kill", name, timeout=20)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter, timeout=30)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(reader), timeout=5)
            for t in (reader, writer, stop):
                if t is not None and not t.done():
                    t.cancel()
            code, state = await _docker("inspect", "--format", "{{json .State}}", name, timeout=15)
            await _docker("rm", "-f", name, timeout=20)
        if was_cancelled:
            raise Cancelled("execution cancelled while the sandbox was running")
        info = json.loads(state) if code == 0 and state.strip().startswith("{") else {}
        out = kept.decode("utf-8", "replace")
        res = RunResult(backend=self.name, seconds=round(time.monotonic() - started, 3), killed=killed,
                        oom_killed=bool(info.get("OOMKilled")))
        line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("HMAP_RESULTS ")), None)
        by_name = {s.name: s for s in steps}
        if line is None:
            res.error = ("the sandbox run was killed at its time limit" if killed else
                         "the sandbox ran out of memory" if res.oom_killed else
                         f"the sandbox gave no result: {out[-600:].strip() or 'no output'}")
            return res
        try:
            raw = json.loads(line[len("HMAP_RESULTS "):])
        except ValueError:
            res.error = "the sandbox result was not readable"
            return res
        for r in raw:
            step = by_name.get(str(r.get("name")))
            if step is None:
                continue
            res.steps.append(StepResult(name=step.name, stage=step.stage, cmd=str(r.get("cmd") or ""),
                                        exit_code=r.get("exit_code"), timed_out=bool(r.get("timed_out")),
                                        output=str(r.get("output") or ""), seconds=float(r.get("seconds") or 0),
                                        files={str(k): str(v) for k, v in (r.get("files") or {}).items()},
                                        skipped=bool(r.get("skipped"))))
        log.info("sandbox run done", backend="docker", steps=len(res.steps), seconds=res.seconds, killed=killed)
        return res

#!/usr/bin/env python3
"""Run untrusted Python code in a locked-down Docker container (Member 8, prototype for Sprint 8 item 8.1).

    python3 samples/testing/sandbox/run_sandbox.py <folder>                 # static + security + unit stages
    python3 samples/testing/sandbox/run_sandbox.py <folder> --script main.py --timeout 10

Limits on every run (the Sprint 8 design, §4):
- ``--network none``: no network at all;
- ``--read-only`` root filesystem; the code lives in a size-capped tmpfs ``/work`` (a writable copy, never the host
  folder) and ``/tmp`` is a small tmpfs;
- ``--user 10001`` (not root), ``--cap-drop ALL``, ``--security-opt no-new-privileges``;
- ``--memory`` / ``--memory-swap`` (no swap escape), ``--cpus``, ``--pids-limit`` (fork bombs);
- a hard wall-clock timeout (the container is killed), and at most ``--max-output`` bytes of output kept.

The folder is streamed in as a tar on stdin, so no host path is ever mounted: this also works with Colima, which
cannot mount external drives. Plain Python 3.11 + the ``docker`` CLI; no project imports.
"""

import argparse
import io
import json
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE = "hmap-sandbox-py:proto"


@dataclass
class Limits:
    timeout_s: float = 30.0
    memory: str = "256m"
    cpus: str = "1"
    pids: int = 64
    max_output: int = 64_000
    work_mb: int = 64


@dataclass
class Result:
    exit_code: int | None
    timed_out: bool
    oom_killed: bool
    output: str
    output_bytes: int
    output_truncated: bool
    seconds: float
    stages: list[dict] = field(default_factory=list)


def ensure_image(rebuild: bool = False) -> None:
    have = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0
    if rebuild or not have:
        subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(HERE)], check=True, stdout=subprocess.DEVNULL)


def tar_folder(folder: Path, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                tar.add(path, arcname=str(path.relative_to(folder)))
        for name, data in (extra or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def run(folder: Path, *, script: str | None = None, stages: list[str] | None = None,
        limits: Limits | None = None) -> Result:
    """Run ``script`` (a file in ``folder``) or the stage pipeline (``stages.py``) in a fresh container."""
    lim = limits or Limits()
    name = f"hmap-sbx-{uuid.uuid4().hex[:12]}"
    if script:
        payload = tar_folder(folder)
        inner = ["sh", "-c", f"cd /work && tar -xf - && exec python {script}"]
    else:
        payload = tar_folder(folder)
        inner = ["python", "/opt/hmap/stages.py", *(stages or [])]
    cmd = ["docker", "run", "-i", "--name", name, "--network", "none", "--read-only",
           "--tmpfs", f"/work:rw,exec,size={lim.work_mb}m,uid=10001,gid=10001",
           "--tmpfs", "/tmp:rw,size=16m,uid=10001,gid=10001",
           "--memory", lim.memory, "--memory-swap", lim.memory, "--cpus", lim.cpus, "--pids-limit", str(lim.pids),
           "--user", "10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", IMAGE, *inner]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    kept = bytearray()
    total = [0]

    def drain() -> None:                       # keep reading (so the container never blocks) but keep only a cap
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(65536), b""):  # type: ignore[union-attr]
            total[0] += len(chunk)
            room = lim.max_output - len(kept)
            if room > 0:
                kept.extend(chunk[:room])

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(payload)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    timed_out = False
    try:
        proc.wait(timeout=lim.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(["docker", "kill", name], capture_output=True)
        proc.wait(timeout=30)
    reader.join(timeout=10)
    seconds = round(time.monotonic() - started, 2)
    state = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", name], capture_output=True, text=True)
    info = json.loads(state.stdout) if state.returncode == 0 and state.stdout.strip() else {}
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    output = kept.decode(errors="replace")
    stages_out: list[dict] = []
    for line in output.splitlines():
        if line.startswith("HMAP_STAGES "):
            stages_out = json.loads(line[len("HMAP_STAGES "):])
    return Result(exit_code=None if timed_out else info.get("ExitCode", proc.returncode), timed_out=timed_out,
                  oom_killed=bool(info.get("OOMKilled")), output=output, output_bytes=total[0],
                  output_truncated=total[0] > lim.max_output, seconds=seconds, stages=stages_out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--script", help="run this file instead of the stage pipeline")
    ap.add_argument("--stages", nargs="*", choices=("static", "security", "unit"))
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--memory", default="256m")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the sandbox image first")
    args = ap.parse_args()
    ensure_image(args.rebuild)
    res = run(args.folder, script=args.script, stages=args.stages,
              limits=Limits(timeout_s=args.timeout, memory=args.memory))
    print(json.dumps(asdict(res), indent=1))
    return 0 if res.exit_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

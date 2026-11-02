"""Which interpreter runs model-written code, and the best-effort macOS sandbox around it (plan D6, Q2/Q3).

The backend's own venv is **never** used for generated code: it has ``hmap`` installed, and ``hmap.core.config``
reads ``<repo>/.env`` (the team keys). Order: ``HMAP_CODING_PYTHON`` → ``data/coding/venv`` (``make coding-venv``:
pytest / fastapi / httpx, no hmap) → the base Python under the backend venv.

On macOS with ``HMAP_CODING_SANDBOX=auto`` every interpreter command runs under ``sandbox-exec`` with a profile that
denies outbound network except localhost (the TCP-chat tests talk to 127.0.0.1), denies reading the project folder
and the user's home, and allows writes only inside the workspace. ``sandbox-exec`` is deprecated by Apple but works;
the hard boundary is Member 8's Docker runner (Sprint 8). Elsewhere (Linux CI) commands run without it.
"""

import shutil
import sys
from pathlib import Path

from hmap.core.config import REPO_ROOT, Settings

CODING_VENV = REPO_ROOT / "data" / "coding" / "venv"


def base_python() -> str:
    exe = getattr(sys, "_base_executable", None) or sys.executable
    if sys.prefix != sys.base_prefix and Path(exe).resolve().is_relative_to(Path(sys.prefix).resolve()):
        exe = str(Path(sys.base_prefix) / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}")
    return exe


def interpreter(settings: Settings) -> str:
    if settings.coding_python:
        return settings.coding_python
    venv = CODING_VENV / "bin" / "python"
    if venv.exists():
        return str(venv)
    return base_python()


def ruff_binary() -> str | None:
    """The backend's ruff: it reads code and never runs it, so it needs no sandbox."""
    local = Path(sys.executable).parent / "ruff"
    return str(local) if local.exists() else shutil.which("ruff")


def sandbox_available(settings: Settings) -> bool:
    return settings.coding_sandbox == "auto" and sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


def _q(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def profile(workspace: Path) -> str:
    ws = Path(workspace).resolve()
    home = Path.home().resolve()
    deny_read = sorted({str(REPO_ROOT.resolve()), str(home)})
    return "\n".join([
        "(version 1)",
        "(allow default)",
        "(deny network-outbound)",
        '(allow network-outbound (remote ip "localhost:*"))',
        "(allow network-outbound (remote unix-socket))",
        # contents (and folder listings) only: the interpreter must still stat its own parent folders
        "(deny file-read-data " + " ".join(f"(subpath {_q(p)})" for p in deny_read) + ")",
        f"(allow file-read-data (subpath {_q(CODING_VENV)}) (subpath {_q(ws)}))",
        "(deny file-write*)",
        f'(allow file-write* (subpath {_q(ws)}) (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/fd/"))',
        "",
    ])


def wrap(argv: list[str], workspace: Path, settings: Settings) -> list[str]:
    if not sandbox_available(settings):
        return argv
    return ["sandbox-exec", "-p", profile(workspace), *argv]

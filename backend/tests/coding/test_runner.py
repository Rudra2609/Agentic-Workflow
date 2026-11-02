"""Item 7.4: the command allow-list, the scrubbed environment, the sandbox around model-written code, limits."""

import asyncio
import sys

import pytest

from hmap.agents.coding.tools import sandbox
from hmap.agents.coding.tools.runner import Runner, normalise
from hmap.agents.coding.workspace import Workspace
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.errors import Cancelled

DARWIN_SANDBOX = pytest.mark.skipif(not (sys.platform == "darwin" and sandbox.sandbox_available(
    Settings.from_env({}))), reason="macOS sandbox-exec only")


@pytest.mark.parametrize("cmd", [
    "sh -c 'echo hi'", "rm -rf .", "curl https://example.com", "python3 -c 'import os'", "python3 -m http.server",
    "python3 -m pip install requests", "pip install requests", "python3 ../outside/evil.py",
    "python3 -m py_compile /etc/hosts", "python /etc/hosts.py", "ruff format .", "ruff check /etc",
    "python -m unittest ../other", "bash", "", "python 'unclosed",
])
async def test_commands_off_the_allow_list_are_denied_and_audited(ws: Workspace, settings: Settings,
                                                                  cmd: str) -> None:
    runner = Runner(ws, settings)
    res = await runner.run(cmd)
    assert res.denied and res.exit_code is None
    assert "DENIED" in res.for_model()
    assert any("denied" in a for a in ws.audit)


async def test_allowed_commands_run_in_the_workspace(ws: Workspace, settings: Settings) -> None:
    ws.write("app.py", "print('hello')\n")
    ws.write("test_app.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n"
                            "        self.assertTrue(True)\n")
    runner = Runner(ws, settings)
    for cmd in ("python3 app.py", "python -m py_compile app.py", "python -m unittest", "pytest -q"):
        res = await runner.run(cmd)
        assert res.ok, (cmd, res.output)
    assert "hello" in (await runner.run("python app.py")).output


async def test_generated_code_sees_no_keys_and_cannot_import_hmap(ws: Workspace, settings: Settings,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAP_GROQ_API_KEYS", "test-value-not-a-real-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-value-2")
    ws.write("probe.py", "import os\nprint(sorted(os.environ))\ntry:\n    import hmap\n    print('HMAP')\n"
                         "except ImportError:\n    print('no hmap')\n")
    res = await Runner(ws, settings).run("python probe.py")
    assert "test-value" not in res.output and "HMAP_" not in res.output and "API_KEY" not in res.output
    assert "no hmap" in res.output


def test_the_backend_venv_is_never_the_coding_interpreter(settings: Settings) -> None:
    exe = sandbox.interpreter(settings)
    if sys.prefix != sys.base_prefix:
        from pathlib import Path
        assert not Path(exe).parent.resolve().is_relative_to(Path(sys.prefix).resolve())


@DARWIN_SANDBOX
async def test_sandbox_blocks_the_env_file_home_network_and_outside_writes(ws: Workspace, settings: Settings) -> None:
    from pathlib import Path
    ws.write("probe.py", f"""import socket
for p in [{str(REPO_ROOT / ".env")!r}, {str(REPO_ROOT / "README.md")!r}, {str(Path.home() / ".zshrc")!r}]:
    try:
        open(p).read(1)
        print("READ", p)
    except OSError as e:
        print("blocked-read", type(e).__name__)
try:
    open("../escape.txt", "w").write("x")
    print("WROTE")
except OSError:
    print("blocked-write")
try:
    socket.create_connection(("1.1.1.1", 80), timeout=2)
    print("NET")
except OSError:
    print("blocked-net")
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen()
c = socket.create_connection(s.getsockname()); a, _ = s.accept(); c.sendall(b"ok"); print("local", a.recv(2))
""")
    res = await Runner(ws, settings).run("python probe.py")
    assert "READ" not in res.output and "WROTE" not in res.output and "NET" not in res.output, res.output
    assert res.output.count("blocked-read") == 3 and "blocked-write" in res.output and "blocked-net" in res.output
    assert "local b'ok'" in res.output                           # the TCP-chat tests need localhost
    assert not (ws.root.parent / "escape.txt").exists()


async def test_endless_loop_is_killed_and_output_flood_capped(ws: Workspace, settings: Settings) -> None:
    ws.write("forever.py", "while True:\n    pass\n")
    ws.write("flood.py", "while True:\n    print('x' * 1000)\n")
    runner = Runner(ws, settings)
    res = await runner.run("python forever.py", timeout=1)
    assert res.timed_out and res.exit_code is None and "TIMED OUT" in res.for_model()
    res = await runner.run("python flood.py")
    assert res.exit_code is None and res.truncated and "killed" in res.output
    assert len(res.for_model()) < 11_000


async def test_cancel_kills_the_running_command(ws: Workspace, settings: Settings) -> None:
    ws.write("forever.py", "import time\nwhile True:\n    time.sleep(0.1)\n")
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.3, stop.set)
    with pytest.raises(Cancelled):
        await Runner(ws, settings).run("python forever.py", timeout=30, cancelled=stop)


def test_normalise_removes_paths_timings_and_addresses(ws: Workspace) -> None:
    text = (f'File "{ws.root}/server.py", line 3\nRan 3 tests in 0.004s\n<obj at 0x7f8a1c2b3d40>\n'
            'File "/opt/homebrew/Cellar/python@3.11/3.11.13/lib/python3.11/unittest/case.py", line 1\n'
            "=== 1 failed in 0.12s ===\nbind ('127.0.0.1', 54321)\nargv = ['count', 'tmpris_eh4i.txt']\n"
            "1 failed in 0.03s")
    out = normalise(text, ws)
    assert str(ws.root) not in out and 'File "server.py"' in out
    assert "Ran 3 tests\n" in out and "0x?" in out and "<python>/lib/python3.11/unittest" in out
    assert "=== 1 failed ===" in out and "('127.0.0.1', N)" in out
    assert "'tmpXXXXXXXX.txt'" in out and out.endswith("1 failed")

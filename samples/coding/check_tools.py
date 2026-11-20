#!/usr/bin/env python3
"""Attack and edge-case checks for the coding agent's tools (Member 7, prepared ahead of Sprint 7 items 7.1, 7.4,
7.5, 7.15). Plain Python 3.11.

    python3 samples/coding/check_tools.py

- path jail: ``..``, absolute paths, symlinks that point out, NUL bytes, writes through a symlinked folder;
- command allow-list: shells, network tools, ``python -c``, other modules, scripts outside the workspace;
- environment: an API key set in the parent process must not reach generated code;
- limits: an endless script is killed, a flood of output is capped;
- edits: exact, create, ambiguous, not found (with a hint), tolerant whitespace / indentation, syntax-breaking
  (atomic: nothing written), outside the workspace, malformed.
"""

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from edits import EditError, apply_text  # noqa: E402
from workspace import JailError, Workspace  # noqa: E402

GOOD = "def greet(name):\n    return 'hi ' + name\n\n\ndef twice(x):\n    return x * 2\n\n\ndef again(x):\n    return x * 2\n"


def block(path: str, search: str, replace: str) -> str:
    return f"{path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"


def denied(fn: Callable[[], object], error: type[Exception] = JailError) -> tuple[bool, str]:
    try:
        fn()
    except error as exc:
        return True, str(exc)
    return False, "was allowed"


def main() -> int:
    rows: list[tuple[str, str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root, outside = base / "ws", base / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "secret.txt").write_text("outside data", encoding="utf-8")
        (root / "app.py").write_text(GOOD, encoding="utf-8")
        (root / "link_out").symlink_to(outside, target_is_directory=True)
        (root / "hosts_link").symlink_to("/etc/hosts")
        ws = Workspace(root)

        # --- path jail ---------------------------------------------------------------------------------------
        for name, rel, op in [
            ("dot-dot read", "../outside/secret.txt", "read"),
            ("nested dot-dot", "sub/../../outside/secret.txt", "read"),
            ("absolute path", "/etc/passwd", "read"),
            ("symlink file out", "hosts_link", "read"),
            ("symlinked folder write", "link_out/planted.py", "write"),
            ("NUL byte", "app.py\0.txt", "read"),
        ]:
            ok, why = denied((lambda r=rel: ws.read(r)) if op == "read" else (lambda r=rel: ws.write(r, "x = 1\n")))
            rows.append(("jail", name, ok and not (outside / "planted.py").exists(), why))
        ws.write("pkg/new_module.py", "x = 1\n")
        rows.append(("jail", "normal nested write allowed", (root / "pkg/new_module.py").exists(), "written"))

        # --- command allow-list ------------------------------------------------------------------------------
        for name, argv in [
            ("shell", ["sh", "-c", "echo hi"]),
            ("rm", ["rm", "-rf", "."]),
            ("network tool", ["curl", "https://example.com"]),
            ("python -c", ["python3", "-c", "import os; os.system('id')"]),
            ("other module", ["python3", "-m", "http.server"]),
            ("pip install", ["python3", "-m", "pip", "install", "requests"]),
            ("script outside", ["python3", "../outside/evil.py"]),
            ("py_compile outside", ["python3", "-m", "py_compile", "/etc/hosts"]),
        ]:
            ok, why = denied(lambda a=argv: ws.check_command(a))
            rows.append(("command", name, ok, why))
        r = ws.run(["python3", "-m", "py_compile", "app.py"])
        rows.append(("command", "py_compile allowed", r.exit_code == 0, f"exit {r.exit_code}"))
        rows.append(("command", "denials are audited", sum(a[2] != "allowed" for a in ws.audit) >= 14,
                     f"{len(ws.audit)} audit entries"))

        # --- environment and limits ----------------------------------------------------------------------------
        os.environ["HMAP_GROQ_API_KEYS"] = "test-value-not-a-real-key"
        (root / "env_dump.py").write_text("import os\nprint(sorted(os.environ))\nprint(open('/proc/self/environ'"
                                          ").read() if os.path.exists('/proc/self/environ') else '')\n",
                                          encoding="utf-8")
        r = ws.run(["python3", "env_dump.py"])
        rows.append(("env", "API key not inherited", "HMAP" not in r.output and "test-value" not in r.output,
                     r.output.splitlines()[0][:70] if r.output else "no output"))
        del os.environ["HMAP_GROQ_API_KEYS"]
        (root / "forever.py").write_text("while True:\n    pass\n", encoding="utf-8")
        r = ws.run(["python3", "forever.py"], timeout=2)
        rows.append(("limits", "endless loop killed", r.timed_out, f"timed_out={r.timed_out}"))
        (root / "flood.py").write_text("import sys\nsys.stdout.write('x' * 5_000_000)\n", encoding="utf-8")
        r = ws.run(["python3", "flood.py"], max_output=10_000)
        rows.append(("limits", "output capped", r.truncated and len(r.output) == 10_000, f"kept {len(r.output)} chars"))

        # --- edits ---------------------------------------------------------------------------------------------
        def edit_case(name: str, text: str, expect_ok: bool, check: Callable[[], bool] = lambda: True,
                      hint: str = "") -> None:
            before = (root / "app.py").read_text(encoding="utf-8")
            try:
                applied = apply_text(ws, text)
                ok, why = expect_ok and check(), f"applied {applied.files} {'; '.join(applied.notes)}".strip()
            except EditError as exc:
                unchanged = (root / "app.py").read_text(encoding="utf-8") == before
                ok, why = (not expect_ok) and unchanged and hint in str(exc), str(exc)
            rows.append(("edit", name, ok, why))

        edit_case("exact match", block("app.py", "    return 'hi ' + name\n", "    return 'hello ' + name\n"), True,
                  lambda: "hello" in (root / "app.py").read_text(encoding="utf-8"))
        edit_case("create new file", block("util.py", "", "def helper():\n    return 1\n"), True,
                  lambda: (root / "util.py").exists())
        edit_case("create over existing", block("app.py", "", "x = 1\n"), False, hint="already exists")
        edit_case("missing file", block("nope.py", "a = 1\n", "a = 2\n"), False, hint="does not exist")
        edit_case("ambiguous match", block("app.py", "    return x * 2\n", "    return x + x\n"), False,
                  hint="matches 2 places")
        edit_case("not found + hint", block("app.py", "def greet(nam):\n", "def greet(n):\n"), False,
                  hint="closest line")
        edit_case("trailing whitespace tolerated", block("app.py", "def twice(x):   \n    return x * 2\n",
                                                         "def twice(x):\n    return 2 * x\n"), True,
                  lambda: "2 * x" in (root / "app.py").read_text(encoding="utf-8"))
        edit_case("indentation shift tolerated", block("app.py", "  def greet(name):\n      return 'hello ' + name\n",
                                                       "  def greet(name):\n      return 'hey ' + name\n"), True,
                  lambda: "def greet(name):\n    return 'hey ' + name" in (root / "app.py").read_text(encoding="utf-8"))
        edit_case("syntax break, atomic", block("util.py", "    return 1\n", "    return 2\n")
                  + block("app.py", "def again(x):\n", "def again(x)\n"), False, hint="SyntaxError")
        rows.append(("edit", "atomic: first block not written", "return 1" in (root / "util.py").read_text(
            encoding="utf-8"), "util.py unchanged"))
        edit_case("edit outside workspace", block("../outside/secret.txt", "outside data\n", "pwned\n"), False,
                  hint="outside the workspace")
        edit_case("malformed block", "app.py\n<<<<<<< SEARCH\nx\n=======\ny\n", False, hint="no SEARCH/REPLACE")

    width = max(len(r[1]) for r in rows)
    for group, name, ok, why in rows:
        print(f"{group:8s} {name:{width}s} {'PASS' if ok else 'FAIL'}  {why[:90]}")
    failed = sum(not r[2] for r in rows)
    print(f"\n{len(rows) - failed}/{len(rows)} checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

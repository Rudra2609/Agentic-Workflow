#!/usr/bin/env python3
"""Build the seeded-failure suite (Member 8, prepared ahead of Sprint 8 item 8.12): the known-good ``good/`` module
plus 15 broken variants, each with one labelled fault. Every edit is written by hand below; the builder refuses to
run if the text it replaces is missing. Plain Python 3.11.

    python3 samples/testing/seeded_failures/build_variants.py     # writes variants/<name>/chatproto.py + labels.json

Categories are the Sprint 8 failure classes (design §4): SYNTAX, IMPORT, ASSERTION, TIMEOUT, CRASH, SECURITY, LINT.
``stage`` says which pipeline stage must catch it (unit = pytest, security = bandit, static = ruff).
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOOD = (HERE / "good" / "chatproto.py").read_text(encoding="utf-8")

# name, category, stage, description, [(text in good/chatproto.py, replacement), ...]
VARIANTS: list[tuple[str, str, str, str, list[tuple[str, str]]]] = [
    ("syntax_error", "SYNTAX", "unit", "missing colon after a function signature",
     [("def frame(message: str) -> bytes:", "def frame(message: str) -> bytes")]),
    ("import_error", "IMPORT", "unit", "imports a module that does not exist",
     [("import threading\n", "import threading\n\nimport chatutils  # noqa: F401\n")]),
    ("name_error", "CRASH", "unit", "a misspelled variable (NameError at run time)",
     [('messages.append(buffer[4:4 + size].decode("utf-8"))', 'messages.append(buffer[4:4 + size].decode(encodng))')]),
    ("off_by_one", "ASSERTION", "unit", "an exactly complete frame is treated as incomplete (< became <=)",
     [("if len(buffer) < 4 + size:", "if len(buffer) <= 4 + size:")]),
    ("swapped_arguments", "ASSERTION", "unit", "/msg returns the text and the target in the wrong order",
     [('return "msg", [target, text]', 'return "msg", [text, target]')]),
    ("race_condition", "ASSERTION", "unit", "the lock was removed and a pause opens a check-then-set race",
     [("        with self._lock:\n            key = nick.lower()\n            if key in self._names:\n"
       "                return False\n            self._names[key] = client_id\n            return True",
       "        key = nick.lower()\n        if key in self._names:\n            return False\n"
       "        time.sleep(0.001)\n        self._names[key] = client_id\n        return True"),
      ("import threading\n", "import threading\nimport time\n")]),
    ("infinite_loop", "TIMEOUT", "unit", "an incomplete frame loops forever instead of waiting for more bytes",
     [("        if len(buffer) < 4 + size:\n            break", "        if len(buffer) < 4 + size:\n            continue")]),
    ("recursion", "CRASH", "unit", "parse_command calls itself without end (RecursionError)",
     [('    line = line.strip()\n    if not line.startswith("/"):',
       '    line = parse_command(line.strip())[1][0]\n    if not line.startswith("/"):')]),
    ("insecure_eval", "SECURITY", "security", "plain text goes through eval() (code injection); tests still pass",
     [('        return "say", [line]', '        return "say", [str(eval(repr(line)))]')]),
    ("shell_injection", "SECURITY", "security", "a nickname is passed to a shell command (shell=True); tests still pass",
     [("def frame(message: str) -> bytes:",
       "def announce(nick: str) -> None:\n    import subprocess\n\n"
       "    subprocess.run(f\"echo welcome {nick}\", shell=True)\n\n\ndef frame(message: str) -> bytes:")]),
    ("hardcoded_secret", "SECURITY", "security", "an admin password in the source code; tests still pass",
     [("MAX_NICK = 16\n", "MAX_NICK = 16\nADMIN_PASSWORD = \"hunter2-admin\"\n")]),
    ("lint_unused_import", "LINT", "static", "an unused import and a bare except; tests still pass",
     [("import threading\n", "import os\nimport threading\n"),
      ("    name, _, rest = line[1:].partition(\" \")\n",
       "    try:\n        name, _, rest = line[1:].partition(\" \")\n    except:\n        raise\n")]),
    ("type_error", "CRASH", "unit", "a str is added to bytes when building a frame (TypeError)",
     [('return len(body).to_bytes(4, "big") + body', 'return len(body).to_bytes(4, "big") + message')]),
    ("swallowed_error", "ASSERTION", "unit", "an invalid nickname returns False instead of raising ProtocolError",
     [('            raise ProtocolError("a nickname is 1-16 letters or digits")', "            return False")]),
    ("not_implemented", "CRASH", "unit", "unregister was left as a stub (NotImplementedError)",
     [("        with self._lock:\n            self._names.pop(nick.lower(), None)",
       '        raise NotImplementedError("unregister")')]),
]


def main() -> None:
    labels = []
    for name, category, stage, description, edits in VARIANTS:
        src = GOOD
        for find, repl in edits:
            assert src.count(find) == 1, (name, find)
            src = src.replace(find, repl)
        out = HERE / "variants" / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "chatproto.py").write_text(src, encoding="utf-8")
        labels.append({"variant": name, "category": category, "stage": stage, "description": description})
    (HERE / "labels.json").write_text(json.dumps(labels, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(labels)} variants")


if __name__ == "__main__":
    main()

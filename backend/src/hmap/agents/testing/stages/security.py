"""Security (item 8.6): bandit inside the Docker sandbox, plus built-in rules that run on the host on every
backend (they parse the code with ``ast`` and never execute it) and a secret-pattern scan. Test files are not
scanned. Skipped bandit checks: B101 (``assert`` is how tests check), B104 (binding 0.0.0.0 is normal for a
server, and the sandbox has no network), B311 (``random`` for non-crypto use).

Known-vulnerable dependencies are checked on the host by :mod:`..deps` (OSV, the pip-audit / npm audit database):
the sandbox has no network. The stage detail says whether the pins were audited.
"""

import ast
import re

from hmap.agents.testing import analyze
from hmap.agents.testing.model import FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step
from hmap.agents.testing.stages import View

BANDIT_SKIP = "B101,B104,B311"
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "an AWS access key"),
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "a Groq API key"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "a Google API key"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "an API secret key"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "a GitHub token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "a private key"),
]
SECRET_NAME = re.compile(r"(pass(word|wd)?|secret|token|api_?key|private_?key)$", re.I)
SHELL_CALLS = {"system", "popen", "call", "run", "Popen", "check_call", "check_output", "getoutput",
               "getstatusoutput"}


def steps(view: View) -> list[Step]:
    if not view.code_files or view.backend != "docker":
        return []
    return [Step(stage="security", name="bandit", kind="bandit", args=["-s", BANDIT_SKIP],
                 timeout=min(60.0, view.stage_timeout))]


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return ""


def scan_source(rel: str, text: str) -> list[FailureRecord]:
    """Built-in rules (a small bandit subset that needs no execution and no extra package)."""
    out: list[FailureRecord] = []

    def add(line: int, msg: str) -> None:
        f = FailureRecord(stage="security", category="SECURITY", file=rel, line=line, message=msg[:300])
        f.hint = analyze.rule_hint(f)
        out.append(f)

    for i, line in enumerate(text.splitlines(), 1):
        for pattern, what in SECRET_PATTERNS:
            if pattern.search(line):
                add(i, f"HMAP-S1 hard-coded secret: {what} in the code")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _name(node.func)
            short = fn.rsplit(".", 1)[-1]
            if fn in ("eval", "exec", "builtins.eval", "builtins.exec"):
                add(node.lineno, f"HMAP-S2 use of {short}(): code injection when the text comes from outside")
            elif short in SHELL_CALLS and (fn.startswith(("os.", "subprocess.", "commands.")) or fn in SHELL_CALLS):
                shell = any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True
                            for k in node.keywords)
                if shell or fn in ("os.system", "os.popen"):
                    add(node.lineno, f"HMAP-S3 {fn}() runs a shell command (shell injection)")
            elif fn in ("pickle.loads", "pickle.load", "marshal.loads", "marshal.load"):
                add(node.lineno, f"HMAP-S4 {fn}() can run code while loading (pickle)")
            elif fn == "yaml.load" and not any(k.arg == "Loader" for k in node.keywords):
                add(node.lineno, "HMAP-S5 yaml.load() without a safe Loader")
            elif fn == "tempfile.mktemp":
                add(node.lineno, "HMAP-S6 tempfile.mktemp() is racy")
            if any(k.arg == "verify" and isinstance(k.value, ast.Constant) and k.value.value is False
                   for k in node.keywords):
                add(node.lineno, "HMAP-S7 TLS certificate check switched off (verify=False, tls)")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) >= 6):
                continue
            for t in targets:
                name = _name(t).rsplit(".", 1)[-1]
                if name and SECRET_NAME.search(name) and not value.value.isupper():
                    add(node.lineno, f"HMAP-S1 hard-coded secret: {name} is set to a fixed string")
    return out


def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]:
    if not view.code_files:
        return StageRecord(name="security", status="skipped", detail="no code files"), []
    failures: list[FailureRecord] = []
    for rel in view.code_files:
        failures.extend(scan_source(rel, view.files[rel]))
    tools = ["built-in rules + secret patterns"]
    seconds = 0.0
    bandit = run.get("bandit")
    if bandit is not None and bandit.unavailable is None and not bandit.skipped:
        seconds = bandit.seconds
        found = analyze.parse_bandit(bandit.files.get(".json", ""))
        seen = {(f.file, f.line) for f in failures}
        failures.extend(f for f in found if (f.file, f.line) not in seen)
        tools.insert(0, "bandit")
        if bandit.timed_out:
            failures.append(FailureRecord(stage="security", category="ENV", message="bandit timed out",
                                          hint="the security scan did not finish; this is not a fault in the code"))
    detail = ", ".join(tools)
    return StageRecord(name="security", status="failed" if failures else "passed", duration_s=round(seconds, 3),
                       detail=detail), failures

#!/usr/bin/env python3
"""Grounding checker for generated documentation (Member 9, prepared ahead of Sprint 9 item 9.6): pull the technical
claims out of a Markdown document and check each one against the facts of the repository (``inspect_repo.py``).
"If there is no Redis in the code, the docs must never say Redis." Plain Python 3.11, no model, no project code.

    python3 samples/docgen/grounding.py samples/docgen/repos/todo_api                 # checks <repo>/README.md
    python3 samples/docgen/grounding.py <repo> some_doc.md

Claim types: TECH (a named technology), ENDPOINT (``GET /todos``), ENV (``TODO_DB_PATH``), PATH (``config/x.yaml``),
SYMBOL (``add_todo()``, ``Room``), FLAG (``--format``), COMMAND (``python app.py``, ``uvicorn app:app``, ``pytest``,
``pip install ...``), PORT (``port 8000``, ``localhost:8000``) and VERSION (``Python 3.11``, ``FastAPI 0.115``).
Claims about *behaviour* ("nicknames are case-sensitive") are out of scope: that needs a model (see the README).
"""

import json
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_repo import inspect  # noqa: E402

# Technology name in prose -> evidence: imported module / declared dependency names, or files ("file:Dockerfile").
TECH: dict[str, list[str]] = {
    "Redis": ["redis", "aioredis"], "PostgreSQL": ["psycopg", "psycopg2", "asyncpg"], "Postgres": ["psycopg",
    "psycopg2", "asyncpg"], "MySQL": ["pymysql", "mysql"], "MongoDB": ["pymongo", "motor"], "SQLite": ["sqlite3"],
    "SQLAlchemy": ["sqlalchemy"], "Docker": ["file:Dockerfile", "file:docker-compose.yml", "file:compose.yaml"],
    "Kubernetes": ["file:k8s/"], "Kafka": ["kafka", "aiokafka"], "RabbitMQ": ["pika", "aio_pika"],
    "Celery": ["celery"], "Flask": ["flask"], "FastAPI": ["fastapi"], "Django": ["django"], "uvicorn": ["uvicorn"],
    "pydantic": ["pydantic"], "pytest": ["pytest"], "asyncio": ["asyncio"], "threads": ["threading"],
    "threading": ["threading"], "WebSocket": ["websockets"], "GraphQL": ["graphene", "strawberry"],
    "JWT": ["jwt", "pyjwt"], "pandas": ["pandas"], "NumPy": ["numpy"], "gRPC": ["grpc"], "TCP": ["socket"],
    "React": ["file:package.json"], "Nginx": ["file:nginx.conf"],
}
NEGATION = re.compile(r"\b(no|not|without|never|nor|instead of)\b", re.I)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"```([a-z]*)\n(.*?)```", re.S)  # only bash/sh/console/plain fences hold commands


@dataclass
class Claim:
    kind: str
    text: str
    grounded: bool
    why: str


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _version_ok(claimed: str, spec: str | None) -> tuple[bool, str]:
    """``Python 3.11`` vs ``>=3.11``; ``FastAPI 0.115`` vs ``==0.115.6``."""
    if not spec:
        return False, "no version is declared in the repository"
    for op, v in re.findall(r"(==|>=|~=|<=|<|>)\s*([\d.]+)", spec):
        c, d = _version_tuple(claimed), _version_tuple(v)
        ok = {"==": d[:len(c)] == c, ">=": c >= d[:len(c)], "~=": c[:len(d) - 1] == d[:len(d) - 1],
              "<": c < d, "<=": c <= d, ">": c > d}[op]
        if not ok:
            return False, f"declared {spec}"
    return True, f"declared {spec}"


class Checker:
    def __init__(self, facts: dict) -> None:
        self.f = facts
        mods = facts["modules"].values()
        self.imports = {i.lower() for m in mods for i in m["imports"]}
        self.deps = {d.replace("-", "_") for d in facts["dependencies"]} | set(facts["dependencies"])
        self.symbols = {s for m in mods for s in m["functions"] + m["classes"]}
        self.routes = {(r["method"], re.sub(r"\{[^}]*\}", "{}", r["path"])) for r in facts["routes"]}
        self.flags = {flag: choices for flags in facts["cli"].values() for flag, choices in flags.items()}

    def path_exists(self, p: str) -> bool:
        p = p.strip("./") if p.startswith("./") else p.rstrip("/")
        return p in self.f["files"] or any(f.startswith(p + "/") for f in self.f["files"]) \
            or p in self.f["file_literals"]

    # --- one check per claim type -------------------------------------------------------------------------------
    def tech(self, name: str) -> Claim:
        for ev in TECH[name]:
            if ev.startswith("file:") and self.path_exists(ev[5:]):
                return Claim("TECH", name, True, f"file {ev[5:]}")
            if not ev.startswith("file:") and (ev in self.imports or ev in self.deps):
                return Claim("TECH", name, True, f"imports/depends on {ev}")
        need = "/".join(e.removeprefix("file:") for e in TECH[name])
        return Claim("TECH", name, False, f"nothing in the code imports, declares or contains {need}")

    def endpoint(self, method: str, path: str) -> Claim:
        path = path.rstrip(".,;:")
        key = (method, re.sub(r"\{[^}]*\}", "{}", path))
        same_path = sorted(m for m, p in self.routes if p == key[1])
        why = "route in the code" if key in self.routes else \
            (f"the code has {'/'.join(same_path)} for this path" if same_path else "no such route in the code")
        return Claim("ENDPOINT", f"{method} {path}", key in self.routes, why)

    def command(self, line: str) -> Claim:
        try:
            argv = shlex.split(line)
        except ValueError:
            return Claim("COMMAND", line, False, "cannot be parsed")
        if not argv:
            return Claim("COMMAND", line, True, "empty")
        tool, args = argv[0], argv[1:]
        if tool in ("python", "python3") and args and args[0].endswith(".py"):
            script = args[0]
            if script not in self.f["files"]:
                return Claim("COMMAND", line, False, f"{script} does not exist")
            known = self.f["cli"].get(script, {})
            for i, a in enumerate(args[1:], 1):
                if a.startswith("--"):
                    if a not in known:
                        return Claim("COMMAND", line, False, f"{script} has no {a} option (has {', '.join(known)})")
                    if known[a] and i + 1 < len(args) and args[i + 1] not in known[a]:
                        return Claim("COMMAND", line, False, f"{a} accepts only {', '.join(known[a])}")
            return Claim("COMMAND", line, True, f"{script} exists" + (" with these options" if known else ""))
        if tool == "uvicorn" and args:
            mod, _, attr = args[0].partition(":")
            ok = f"{mod}.py" in self.f["files"] and ("uvicorn" in self.deps or "uvicorn" in self.imports)
            return Claim("COMMAND", line, ok, f"{mod}.py " + ("exists" if ok else "does not exist / no uvicorn"))
        if tool == "pytest":
            ok = bool(self.f["tests"]) and all(self.path_exists(a) for a in args if not a.startswith("-"))
            return Claim("COMMAND", line, ok, f"{len(self.f['tests'])} test file(s)")
        if tool == "pip" and args[:1] == ["install"]:
            if "-r" in args:
                f = args[args.index("-r") + 1]
                return Claim("COMMAND", line, self.path_exists(f), f"{f} " + ("exists" if self.path_exists(f)
                                                                                   else "does not exist"))
            if "-e" in args:
                target = args[args.index("-e") + 1]
                extras = re.findall(r"\[([^\]]*)\]", target)
                missing = [e for x in extras for e in x.split(",") if e.strip() not in self.f["extras"]]
                ok = "pyproject.toml" in self.f["files"] and not missing
                return Claim("COMMAND", line, ok, "pyproject.toml" + (f" has no [{', '.join(missing)}] extra"
                                                                     if missing else " exists"))
        return Claim("COMMAND", line, True, "not checked (unknown tool)")

    # --- claim extraction -----------------------------------------------------------------------------------------
    def check(self, markdown: str) -> list[Claim]:
        claims: list[Claim] = []
        for lang, block in FENCE.findall(markdown):
            if lang not in ("", "bash", "sh", "shell", "console"):
                continue  # mermaid, json, python examples: not commands (item 9.7 runs code examples in the sandbox)
            claims += [self.command(line.strip()) for line in block.splitlines() if line.strip()
                       and not line.lstrip().startswith("#")]
        prose = FENCE.sub("", markdown)
        for span in CODE_SPAN.findall(prose):
            claims += self.span(span)
        plain = CODE_SPAN.sub("", prose)
        for sentence in re.split(r"(?<=[.!?:])\s+|\n", plain):
            for name in TECH:
                for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", sentence):
                    if not NEGATION.search(sentence[:m.start()]):  # "does not need Docker" is not a claim of Docker
                        claims.append(self.tech(name))
            for m in re.finditer(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s|,)`]*)", sentence):
                claims.append(self.endpoint(m.group(1), m.group(2)))
            for m in re.finditer(r"\b(?:port\s+|localhost:|127\.0\.0\.1:)(\d{2,5})\b", sentence, re.I):
                port = int(m.group(1))
                claims.append(Claim("PORT", m.group(0), port in self.f["ports"],
                                    f"ports in the code: {self.f['ports'] or 'none'}"))
            for m in re.finditer(r"\bPython\s+(\d+\.\d+)", sentence):
                claims.append(Claim("VERSION", m.group(0), *_version_ok(m.group(1), self.f["python_requires"])))
            for m in re.finditer(r"\b([A-Za-z][\w.-]+)\s+v?(\d+\.\d+(?:\.\d+)?)\b", sentence):
                dep = m.group(1).lower()
                if dep != "python" and (dep in self.f["dependencies"] or dep in {t.lower() for t in TECH}):
                    claims.append(Claim("VERSION", m.group(0), *_version_ok(m.group(2),
                                                                           self.f["dependencies"].get(dep))))
        return claims

    def span(self, s: str) -> list[Claim]:
        """One inline code span: a command, endpoint, flag, env var, symbol or path."""
        s = s.strip()
        if re.match(r"(python3?|uvicorn|pytest|pip)\b", s):
            return [self.command(s)]
        if m := re.fullmatch(r"(GET|POST|PUT|PATCH|DELETE)\s+(/\S*)", s):
            return [self.endpoint(m.group(1), m.group(2))]
        if re.fullmatch(r"--[\w-]+(?:\s.*)?", s):
            flag = s.split()[0]
            return [Claim("FLAG", flag, flag in self.flags, "argparse option" if flag in self.flags
                          else "no such command-line option")]
        if re.fullmatch(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", s):
            return [Claim("ENV", s, s in self.f["env"], "read by the code" if s in self.f["env"]
                          else "the code never reads this variable")]
        if m := re.fullmatch(r"([A-Za-z_]\w*)\(\)", s):
            return [Claim("SYMBOL", s, m.group(1) in self.symbols, "defined" if m.group(1) in self.symbols
                          else "no function with this name")]
        if re.fullmatch(r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+|[A-Z][a-z]{2,}", s):  # TodoIn, ProtocolError, Room
            return [Claim("SYMBOL", s, s in self.symbols, "defined" if s in self.symbols
                          else "no class or function with this name")]
        if not s.startswith("/") and " " not in s and ("/" in s or re.search(r"\.(py|toml|txt|md|json|ya?ml|cfg|"
                                                                                   r"ini|csv|db|html|sh|env)$", s)):
            return [Claim("PATH", s, self.path_exists(s), "exists / used by the code" if self.path_exists(s)
                          else "no such file or folder")]
        return []


def check_doc(repo: Path, markdown: str) -> list[Claim]:
    return Checker(inspect(repo)).check(markdown)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    repo = Path(sys.argv[1])
    doc = Path(sys.argv[2]) if len(sys.argv) > 2 else repo / "README.md"
    found = check_doc(repo, doc.read_text(encoding="utf-8"))
    for c in found:
        print(f"{'ok ' if c.grounded else 'BAD'} {c.kind:8s} {c.text[:60]:60s} {c.why}")
    bad = [asdict(c) for c in found if not c.grounded]
    print(f"\n{len(found) - len(bad)}/{len(found)} claims grounded" + (f"; ungrounded: {json.dumps(bad)}" if bad
                                                                         else ""))
    sys.exit(1 if bad else 0)

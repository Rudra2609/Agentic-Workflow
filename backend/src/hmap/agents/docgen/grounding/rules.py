"""Rule layer of the grounding checker (Sprint 9 item 9.6, plan D7; ported from ``samples/docgen/grounding.py``).

Pulls the concrete technical claims out of a Markdown document and checks each one against the :class:`Facts`:

    TECH      a named technology ("Redis", "PostgreSQL", "Docker")    ENDPOINT  ``GET /todos/{id}``
    ENV       ``TODO_DB_PATH``                                         PATH      ``config/settings.toml``
    SYMBOL    ``add_todo()``, ``TodoIn``                                FLAG      ``--format``
    COMMAND   ``python app.py --port 8000``, ``make demo``, ``npm run build``, ``pip install -e ".[dev]"``
    PORT      "port 8000", ``localhost:8000``                          VERSION   "Python 3.11", "FastAPI 0.115"
    CITATION  ``server.py::broadcast`` (summaries cite the symbols they describe)

"If there is no Redis in the code, the docs must never say Redis." Negations are respected ("does not need
Docker" claims nothing); text in curly quotes (“…”) is a quotation, e.g. a requirement of the assignment, not a
claim. No model: free, offline, deterministic. Behaviour claims ("nicknames are case-sensitive") need the model
layer (``behaviour.py``).
"""

import builtins
import fnmatch
import re
import shlex
from dataclasses import dataclass

from hmap.agents.docgen.model import Claim, Facts

# Technology in prose -> evidence: imported module / declared dependency names, "file:<path>", "env:<VAR>",
# "tech:<technology>" (manifests.py: docker, node, javascript) or "service:<compose service>".
TECH: dict[str, list[str]] = {
    "Redis": ["redis", "aioredis", "service:redis"],
    "PostgreSQL": ["psycopg", "psycopg2", "asyncpg", "service:postgres", "service:db"],
    "Postgres": ["psycopg", "psycopg2", "asyncpg", "service:postgres", "service:db"],
    "pgvector": ["pgvector", "file:infra/postgres/init.sql"],
    "MySQL": ["pymysql", "mysql", "service:mysql"], "MongoDB": ["pymongo", "motor", "service:mongo"],
    "SQLite": ["sqlite3", "aiosqlite"], "SQLAlchemy": ["sqlalchemy"], "Alembic": ["alembic"],
    "Docker": ["tech:docker"], "Docker Compose": ["tech:docker"], "Kubernetes": ["file:k8s/", "file:helm/"],
    "Kafka": ["kafka", "aiokafka", "service:kafka"], "RabbitMQ": ["pika", "aio_pika", "aio-pika", "service:rabbitmq"],
    "Celery": ["celery"], "Flask": ["flask"], "FastAPI": ["fastapi"], "Django": ["django"], "uvicorn": ["uvicorn"],
    "Starlette": ["starlette", "fastapi"], "pydantic": ["pydantic"], "pytest": ["pytest"], "asyncio": ["asyncio"],
    "threads": ["threading"], "threading": ["threading"], "multiprocessing": ["multiprocessing"],
    "WebSocket": ["websockets", "websocket", "fastapi"], "GraphQL": ["graphene", "strawberry"],
    "JWT": ["jwt", "pyjwt", "jose"], "OAuth": ["authlib", "oauthlib"], "pandas": ["pandas"], "NumPy": ["numpy"],
    "gRPC": ["grpc", "grpcio"],
    "httpx": ["httpx"], "requests": ["requests"], "aiohttp": ["aiohttp"], "Jinja": ["jinja2"],
    "React": ["react"], "Express": ["express"], "Fastify": ["fastify"], "Koa": ["koa"], "Jest": ["jest"],
    "Mocha": ["mocha"], "Vitest": ["vitest"], "JavaScript": ["tech:javascript"], "Next.js": ["next"],
    "TypeScript": ["typescript"], "Node.js": ["tech:node"],
    "Node": ["tech:node"], "npm": ["tech:node"], "Vite": ["vite"], "Tailwind": ["tailwindcss"],
    "Nginx": ["file:nginx.conf"], "Ollama": ["ollama", "env:OLLAMA_BASE_URL"], "OpenAI": ["openai"],
    "LangChain": ["langchain"], "OpenTelemetry": ["opentelemetry", "opentelemetry-api", "opentelemetry-sdk"],
    "Prometheus": ["prometheus_client", "prometheus-client", "service:prometheus"],
    "Grafana": ["service:grafana"], "Jaeger": ["service:jaeger"], "networkx": ["networkx"],
    "Hypothesis": ["hypothesis"], "mypy": ["mypy"], "ruff": ["ruff"], "Click": ["click"], "Typer": ["typer"],
    "argparse": ["argparse"], "curses": ["curses"], "tkinter": ["tkinter"], "Selenium": ["selenium"],
    "Playwright": ["playwright"], "boto3": ["boto3"], "AWS": ["boto3", "aws-cdk-lib"], "S3": ["boto3"],
}
NEGATION = re.compile(r"\b(no|not|without|never|nor|instead of|isn't|doesn't|don't|cannot|can't|neither|avoid\w*|"
                      r"rather than|unlike|replac\w* by)\b", re.I)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
QUOTE = re.compile(r"\u201c[^\u201d\n]*\u201d")       # “…”: a quotation (an assignment's requirement), not a claim
FENCE = re.compile(r"^[ \t]*```([\w+-]*)[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)   # may be indented (in a list)
SHELL_FENCES = ("", "bash", "sh", "shell", "console", "zsh", "text")
COMMON_WORDS = {"requests"}                        # library names that are also ordinary English words
DEV_TOOLS = {"pytest", "coverage", "ruff", "black", "mypy", "flake8", "isort", "pre-commit", "build", "twine", "pip",
             "pip-tools", "wheel", "setuptools", "tox", "nox", "hypothesis", "pytest-cov", "uv", "virtualenv"}
IMPLIED_PORTS = {"fastapi": 8000, "uvicorn": 8000, "django": 8000, "flask": 5000}   # the framework's own default
CONVENTIONAL = re.compile(r"(LICEN[CS]E|CHANGELOG|CONTRIBUTING|NOTICE|AUTHORS|CODE_OF_CONDUCT|SECURITY)"
                          r"(\.(md|txt|rst))?")
BUILTINS = set(dir(builtins))
COMMAND_START = re.compile(r"(python3?|uvicorn|pytest|pip3?|uv|make|npm|npx|node|docker|curl|cd|scripts/|\./)\b")


@dataclass
class Located:
    """A sentence and where it sits in the document (1-based line)."""

    text: str
    line: int


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def version_ok(claimed: str, spec: str | None) -> tuple[bool, str]:
    """``Python 3.11`` vs ``>=3.11``; ``FastAPI 0.115`` vs ``==0.115.6``; ``^18.3.1`` (npm) vs ``18.3``."""
    if not spec:
        return False, "no version is declared in the repository"
    spec = spec.strip()
    if re.fullmatch(r"[\^~]?\d[\w.]*", spec):                     # npm "18.3.1" / "^18.3.1"
        spec = "==" + spec.lstrip("^~") if not spec.startswith(("^", "~")) else ">=" + spec[1:]
    rules = re.findall(r"(==|>=|~=|<=|<|>)\s*([\d.]+)", spec)
    if not rules:
        return False, f"declared {spec}"
    for op, v in rules:
        c, d = _version_tuple(claimed), _version_tuple(v)
        ok = {"==": d[:len(c)] == c, ">=": c >= d[:len(c)], "~=": c[:len(d) - 1] == d[:len(d) - 1],
              "<": c < d, "<=": c <= d, ">": c > d}[op]
        if not ok:
            return False, f"declared {spec}"
    return True, f"declared {spec}"


def _norm_path(path: str) -> str:
    return re.sub(r"\{[^}]*\}|<[^>]*>|:[A-Za-z_]\w*", "{}", path.rstrip("/") or "/")


class Checker:
    def __init__(self, facts: Facts) -> None:
        self.f = facts
        mods = facts.modules.values()
        self.imports = {i.lower() for m in mods for i in m.imports}
        self.deps = {d.replace("-", "_") for d in facts.dependencies} | set(facts.dependencies)
        self.symbols = facts.symbol_names() | {n for m in mods for n in m.functions + m.classes}
        self.constants = {n for m in mods for n in m.constants}
        # a framework's default port counts only when the code names no port itself (Flask 5000 vs the code's 5001)
        self.ports = set(facts.ports) or {p for lib, p in IMPLIED_PORTS.items() if lib in self.imports
                                          or lib in self.deps}
        self.imported = {n for m in mods for n in m.imported_names}
        self.routes = {(r.method, _norm_path(r.path)) for r in facts.routes}
        self.flags = {flag: choices for flags in facts.cli.values() for flag, choices in flags.items()}
        self.files = set(facts.files)
        self.dirs = {"/".join(f.split("/")[:i]) for f in facts.files for i in range(1, f.count("/") + 1)}
        self.services = {s.lower() for s in facts.services}
        self.techs = {t.lower() for t in facts.technologies}
        self.by_module = {m.module: m for m in mods}
        self.top_packages = {m.module.split(".")[0] for m in mods if "." in m.module}
        self.by_path = dict(facts.modules)

    # --- evidence ----------------------------------------------------------------------------------------------
    def path_exists(self, p: str) -> bool:
        p = p.strip().strip("'\"")
        p = p[2:] if p.startswith("./") else p
        p = p.rstrip("/")
        if not p:
            return False
        if re.search(r"<[^>]+>|\{[^}]+\}|\*", p):              # docs/members/<N>/x.md: a placeholder matches any name
            rx = re.compile("(^|.*/)" + re.sub(r"<[^>]+>|\{[^}]+\}|\\\*", "[^/]+", re.escape(p)) + "$")
            return any(rx.match(x) for x in (*self.files, *self.dirs))
        return p in self.files or p in self.dirs or p in self.f.file_literals or \
            any(f.endswith("/" + p) for f in self.files) or any(d.endswith("/" + p) for d in self.dirs) or \
            self.ignored(p)

    def ignored(self, p: str) -> bool:
        """Git-ignored paths (``.env``, ``data/``, ``logs/``) are made at run time: mentioning them is fine."""
        return any(fnmatch.fnmatch(p, pat.rstrip("/")) or fnmatch.fnmatch(p.split("/")[0], pat.rstrip("/"))
                   for pat in self.f.ignored)

    def evidence(self, ev: str) -> str | None:
        kind, _, value = ev.partition(":") if ev.split(":", 1)[0] in ("file", "env", "tech", "service") else \
            ("", "", ev)
        if kind == "file":
            return f"file {value}" if self.path_exists(value) else None
        if kind == "env":
            return f"reads {value}" if value in self.f.env else None
        if kind == "tech":
            return f"{value} files in the repository" if value in self.techs else None
        if kind == "service":
            return f"compose service {value}" if value in self.services else None
        key = value.lower()
        if key in self.imports or key in self.deps or key.replace("-", "_") in self.deps:
            return f"imports / depends on {value}"
        return None

    # --- one check per claim type -------------------------------------------------------------------------------
    def tech(self, name: str) -> Claim:
        for ev in TECH[name]:
            if found := self.evidence(ev):
                return Claim(kind="TECH", text=name, verdict="grounded", why=found)
        need = "/".join(e.split(":", 1)[-1] for e in TECH[name])
        return Claim(kind="TECH", text=name, verdict="ungrounded",
                     why=f"nothing in the code imports, declares or contains {need}")

    def endpoint(self, method: str, path: str) -> Claim:
        path = path.rstrip(".,;:")
        key = (method, _norm_path(path))
        if key in self.routes:
            return Claim(kind="ENDPOINT", text=f"{method} {path}", verdict="grounded", why="route in the code")
        segs = key[1].split("/")
        for m, p in self.routes:                       # /todos/1 is the route /todos/{todo_id}
            rs = p.split("/")
            if m == method and len(rs) == len(segs) and all(r == c or r == "{}" for r, c in zip(rs, segs,
                                                                                               strict=True)):
                return Claim(kind="ENDPOINT", text=f"{method} {path}", verdict="grounded", why=f"route {p}")
        same = sorted(m for m, p in self.routes if p == key[1])
        why = f"the code has {'/'.join(same)} for this path" if same else "no such route in the code"
        return Claim(kind="ENDPOINT", text=f"{method} {path}", verdict="ungrounded", why=why)

    def _ok(self, kind: str, text: str, ok: bool, why: str) -> Claim:
        return Claim(kind=kind, text=text, verdict="grounded" if ok else "ungrounded", why=why)

    def command(self, line: str) -> Claim:
        line = re.sub(r"^\$\s*", "", line.strip())
        line = re.split(r"\s+(?:&&|\|\||;|\|)\s+", line)[0]       # first command of a pipeline / chain
        try:
            argv = shlex.split(line, comments=True)
        except ValueError:
            return self._ok("COMMAND", line, False, "cannot be parsed")
        while argv and re.fullmatch(r"[A-Z_][A-Z0-9_]*=\S*", argv[0]):     # HMAP_LLM_MODE=replay make demo
            env = argv.pop(0).split("=", 1)[0]
            if env not in self.f.env and not env.startswith(("PATH", "PYTHONPATH")):
                return self._ok("COMMAND", line, False, f"the code never reads {env}")
        if not argv:
            return Claim(kind="COMMAND", text=line, verdict="unchecked", why="empty")
        tool, args = argv[0], argv[1:]
        if tool in ("uv",) and args[:1] == ["run"]:
            tool, args = (args[1], args[2:]) if len(args) > 1 else ("", [])
            if tool and tool in self.f.scripts:
                return self._ok("COMMAND", line, True, f"script {tool} in pyproject.toml")
        if tool in ("python", "python3") and args[:1] == ["-m"] and len(args) > 1:
            mod = args[1]
            if mod in ("pytest", "pip", "venv", "http.server", "unittest"):
                return self.command(" ".join([mod if mod != "pip" else "pip", *args[2:]]))
            run_mod = self.by_module.get(mod) or next((m for m in self.f.modules.values()
                                                        if m.module.endswith("." + mod)), None)
            if run_mod is None:
                return self._ok("COMMAND", line, False, f"module {mod} does not exist")
            flags = [a.split("=", 1)[0] for a in args[2:] if a.startswith("-") and a not in ("-h", "--help")]
            options = self.f.cli.get(run_mod.path, {})
            bad = [f for f in flags if f not in options]
            return self._ok("COMMAND", line, not bad, f"module {mod} exists" if not bad else
                            f"{run_mod.path} has no {', '.join(bad)} option (has {', '.join(options) or 'no options'})")
        if tool in ("python", "python3") and args and args[0].endswith(".py"):
            script = args[0].removeprefix("./")
            if not self.path_exists(script):
                return self._ok("COMMAND", line, False, f"{script} does not exist")
            target = next((f for f in self.f.files if f == script or f.endswith("/" + script)), script)
            known = self.f.cli.get(target, {})
            for i, a in enumerate(args[1:], 1):
                if a.startswith("-") and a not in ("-h", "--help"):
                    flag = a.split("=", 1)[0]
                    if flag not in known:
                        has = ", ".join(known) or "no options"
                        return self._ok("COMMAND", line, False, f"{script} has no {flag} option (has {has})")
                    value = a.split("=", 1)[1] if "=" in a else (args[i + 1] if i + 1 < len(args) else None)
                    if known[flag] and value is not None and value not in known[flag]:  # type: ignore[operator]
                        return self._ok("COMMAND", line, False, f"{flag} accepts only {', '.join(known[flag] or [])}")
            return self._ok("COMMAND", line, True, f"{script} exists" + (" with these options" if known else ""))
        if tool == "uvicorn" and args:
            mod = args[0].partition(":")[0]
            app_mod = self.by_module.get(mod)
            exists = app_mod is not None or self.path_exists(mod.replace(".", "/") + ".py")
            asgi = app_mod is not None and bool({"fastapi", "starlette"} & set(app_mod.imports))
            ok = exists and ("uvicorn" in self.deps or "uvicorn" in self.imports or asgi)
            why = ("exists, uvicorn declared" if "uvicorn" in self.deps or "uvicorn" in self.imports
                   else "is an ASGI app (FastAPI); uvicorn is not declared") if ok else \
                "does not exist / no uvicorn dependency"
            return self._ok("COMMAND", line, ok, f"module {mod} {why}")
        if tool == "pytest":
            paths = [a for a in args if (not a.startswith("-") and not re.fullmatch(r"[\w\s]+", a)) or "/" in a]
            ok = bool(self.f.tests) and all(self.path_exists(a.split("::")[0]) for a in paths)
            return self._ok("COMMAND", line, ok, f"{len(self.f.tests)} test file(s)")
        if tool in ("pip", "pip3") and args[:1] == ["install"]:
            if "-r" in args and args.index("-r") + 1 < len(args):
                f = args[args.index("-r") + 1]
                return self._ok("COMMAND", line, self.path_exists(f), f"{f} " + (
                    "exists" if self.path_exists(f) else "does not exist"))
            local = next((a for a in args[1:] if a == "." or a.startswith((".[", "./"))), None)
            if ("-e" in args and args.index("-e") + 1 < len(args)) or local:
                spec = args[args.index("-e") + 1] if "-e" in args else local or "."
                extras = re.findall(r"\[([^\]]*)\]", spec)
                missing = [e.strip() for x in extras for e in x.split(",") if e.strip() not in self.f.extras]
                has_project = "pyproject.toml" in self.files or "setup.py" in self.files
                reason = ("there is no pyproject.toml or setup.py" if not has_project else
                          f"pyproject.toml has no [{', '.join(missing)}] extra" if missing else "pyproject.toml exists")
                return self._ok("COMMAND", line, has_project and not missing, reason)
            pkgs = [a for a in args[1:] if not a.startswith("-")]
            if any("/" in p or p.endswith((".whl", ".tar.gz", ".zip")) for p in pkgs):
                return Claim(kind="COMMAND", text=line, verdict="unchecked", why="installs a built file")
            allowed = {d.replace("_", "-") for d in self.f.dependencies} | {i.replace("_", "-") for i in self.imports} \
                | DEV_TOOLS | ({"uvicorn"} if "fastapi" in self.imports else set())
            unknown = [p for p in pkgs if re.split(r"[<>=\[~]", p)[0].lower().replace("_", "-") not in allowed]
            return self._ok("COMMAND", line, not unknown, "declared or imported by the code" if not unknown
                            else f"neither declared nor imported by the code: {', '.join(unknown)}")
        if tool == "make":
            targets = [a for a in args if not a.startswith("-") and "=" not in a] or ["(default)"]
            if not self.f.make_targets:
                return self._ok("COMMAND", line, False, "there is no Makefile")
            missing = [t for t in targets if t != "(default)" and t not in self.f.make_targets]
            return self._ok("COMMAND", line, not missing, "Makefile target(s)" if not missing
                            else f"the Makefile has no {', '.join(missing)} target")
        if tool in ("npm", "pnpm", "yarn") and args:
            if args[0] in ("ci", "install", "i"):
                return self._ok("COMMAND", line, "package.json" in {f.rsplit("/", 1)[-1] for f in self.files},
                                "package.json")
            script = args[1] if args[0] == "run" and len(args) > 1 else args[0]
            ok = f"npm run {script}" in self.f.scripts
            return self._ok("COMMAND", line, ok, f"package.json script {script}" + ("" if ok else " does not exist"))
        if tool == "docker":
            if args[:1] == ["compose"] or tool == "docker-compose":
                return self._ok("COMMAND", line, "docker" in self.techs and bool(self.f.services), "compose file")
            return self._ok("COMMAND", line, "docker" in self.techs, "Dockerfile" if "docker" in self.techs
                            else "no Dockerfile or compose file")
        if tool == "curl":
            url = next((a for a in args if a.startswith("http")), "")
            m = re.match(r"https?://(?:localhost|127\.0\.0\.1)(?::(\d+))?(/[^?\s]*)?", url)
            if not m:
                return Claim(kind="COMMAND", text=line, verdict="unchecked", why="not a local URL")
            method = "GET"
            if "-X" in args and args.index("-X") + 1 < len(args):
                method = args[args.index("-X") + 1].upper()
            elif any(a in ("-d", "--data", "--json", "-F") for a in args):
                method = "POST"
            if m.group(1) and int(m.group(1)) not in self.ports:
                return self._ok("COMMAND", line, False, f"port {m.group(1)} is not a port of the code")
            ep = self.endpoint(method, m.group(2) or "/")
            return self._ok("COMMAND", line, ep.grounded, ep.why)
        if tool == "cd" and args:
            if self.path_exists(args[0]) or args[0] in ("..", "~", "-"):
                return self._ok("COMMAND", line, True, "folder")
            if "/" not in args[0].strip("/"):
                return Claim(kind="COMMAND", text=line, verdict="unchecked", why="probably the folder a clone creates")
            return self._ok("COMMAND", line, False, "no such folder")
        if tool.startswith(("scripts/", "./", "bin/")) or tool.endswith(".sh"):
            return self._ok("COMMAND", line, self.path_exists(tool), f"{tool} " + (
                "exists" if self.path_exists(tool) else "does not exist"))
        if tool in self.f.scripts:
            return self._ok("COMMAND", line, True, "console script in pyproject.toml")
        return Claim(kind="COMMAND", text=line, verdict="unchecked", why="not checked (unknown tool)")

    def span(self, s: str) -> list[Claim]:
        """One inline code span: a command, endpoint, flag, env var, symbol, citation or path."""
        s = s.strip()
        if m := re.fullmatch(r"([\w./-]+\.py)::([A-Za-z_][\w.]*)", s):
            return [self.citation(m.group(1), m.group(2))]
        if COMMAND_START.match(s) and (" " in s or s.startswith(("make", "pytest", "scripts/", "./"))):
            return [self.command(s)]
        if m := re.fullmatch(r"(GET|POST|PUT|PATCH|DELETE)\s+(/\S*)", s):
            return [self.endpoint(m.group(1), m.group(2))]
        if re.fullmatch(r"--[\w-]+(?:[ =].*)?", s):
            flag = re.split(r"[ =]", s)[0]
            return [self._ok("FLAG", flag, flag in self.flags, "command-line option" if flag in self.flags
                             else "no such command-line option")]
        if "://" in s or re.fullmatch(r"\.\w{1,5}", s):          # a URL, a bare extension: not a path claim
            return []
        if m := re.fullmatch(r"([A-Z][A-Z0-9]*_[A-Z0-9_]+)(=.*)?", s):
            name = m.group(1)
            if name in self.constants and name not in self.f.env:
                return [self._ok("SYMBOL", name, True, "a constant in the code")]
            return [self._ok("ENV", name, name in self.f.env, "read by the code" if name in self.f.env
                             else "the code never reads this variable")]
        if CONVENTIONAL.fullmatch(s):
            ok = self.path_exists(s) or any(f.split("/")[-1].upper().startswith(s.split(".")[0]) for f in self.files)
            return [self._ok("PATH", s, ok, "exists" if ok else "no such file")]
        if re.search(r"\(.*[\"'].*\)", s):                      # app.route("/report"): code, not a symbol claim
            return []
        if m := re.fullmatch(r"(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)\((?:[^()]*)\)", s):
            if m.group(1) in BUILTINS or re.match(r"(str|int|float|bytes|list|dict|set|tuple)\.", s):
                return [self._ok("SYMBOL", s, True, "a Python built-in")]
            if m.group(1) in self.imported and m.group(1) not in self.symbols:
                return [self._ok("SYMBOL", s, True, "imported from a library")]
            return [self._ok("SYMBOL", s, m.group(1) in self.symbols, "defined" if m.group(1) in self.symbols
                             else "no function with this name")]
        if re.fullmatch(r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+", s):     # TodoIn, ProtocolError (CamelCase only)
            if s in BUILTINS:
                return [self._ok("SYMBOL", s, True, "a Python built-in")]
            if s in self.imported and s not in self.symbols:
                return [self._ok("SYMBOL", s, True, "imported from a library")]
            return [self._ok("SYMBOL", s, s in self.symbols, "defined" if s in self.symbols
                             else "no class or function with this name")]
        if s in self.by_module or (re.fullmatch(r"[a-z_][\w]*(\.[a-z_]\w*)+", s) and any(
                m.startswith(s + ".") for m in self.by_module)):
            return [self._ok("SYMBOL", s, True, "a module / package of the repository")]
        if re.fullmatch(r"[a-z_]\w*(\.[a-z_]\w*)+", s) and s.split(".")[0] in self.top_packages:
            return [self._ok("SYMBOL", s, False, f"no module {s} in the repository")]
        if not s.startswith(("/", "http")) and " " not in s and ("/" in s or re.search(
                r"\.(py|toml|txt|md|json|ya?ml|cfg|ini|csv|db|html|sh|env|example|ts|tsx|js|sql)$", s)):
            ok = self.path_exists(s)
            return [self._ok("PATH", s, ok, "exists / used by the code" if ok else "no such file or folder")]
        return []

    def citation(self, path: str, name: str) -> Claim:
        mod = self.by_path.get(path) or next((m for p, m in self.by_path.items() if p.endswith("/" + path)), None)
        if mod is None:
            return self._ok("CITATION", f"{path}::{name}", False, f"{path} is not a module of the repository")
        names = {s.name for s in mod.symbols} | {f"{s.parent}.{s.name}" for s in mod.symbols if s.parent} | \
            set(mod.functions) | {r.function for r in self.f.routes if r.file == mod.path}
        ok = name in names or name.split(".")[-1] in names
        return self._ok("CITATION", f"{path}::{name}", ok, f"defined in {path}" if ok else f"{path} has no {name}")

    # --- claim extraction -----------------------------------------------------------------------------------------
    def check(self, markdown: str, doc: str = "") -> list[Claim]:
        claims: list[Claim] = []
        for m in FENCE.finditer(markdown):
            lang, block = m.group(1).lower(), m.group(2)
            if lang not in SHELL_FENCES:
                continue        # mermaid, json, python examples: not commands (examples.py runs code examples)
            first = markdown.count("\n", 0, m.start()) + 2
            for i, line in joined_lines(block):
                if line.strip() and not line.lstrip().startswith("#"):
                    claims.append(self._at(self.command(line.strip()), doc, line.strip(), first + i))
        prose = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), markdown)
        prose = QUOTE.sub("“…”", prose)
        for located in sentences(prose):
            sentence = located.text
            for span in CODE_SPAN.findall(sentence):
                for c in self.span(span):
                    claims.append(self._at(c, doc, sentence, located.line))
            plain = CODE_SPAN.sub(" ", sentence)
            plain = re.sub(r"\]\([^)]*\)", "]", plain)               # link targets are paths, not prose
            for name in TECH:
                if name in COMMON_WORDS and not re.search(rf"\b{name}\s+(library|package|module)\b", plain, re.I):
                    continue                    # "feature requests" is not the requests library
                for t in re.finditer(rf"(?<![\w./-]){re.escape(name)}(?![\w-])", plain):
                    if not NEGATION.search(plain[max(0, t.start() - 60):t.start()]):
                        claims.append(self._at(self.tech(name), doc, sentence, located.line))
                        break
            for e in re.finditer(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s|,)`]*)", plain):
                claims.append(self._at(self.endpoint(e.group(1), e.group(2)), doc, sentence, located.line))
            for p in re.finditer(r"\b(?:port\s+|localhost:|127\.0\.0\.1:)(\d{2,5})\b", plain, re.I):
                port = int(p.group(1))
                c = self._ok("PORT", p.group(0), port in self.ports,
                             f"ports in the code: {', '.join(map(str, self.f.ports)) or 'none'}")
                claims.append(self._at(c, doc, sentence, located.line))
            for v in re.finditer(r"\bPython\s+(\d+\.\d+)", plain):
                ok, why = version_ok(v.group(1), self.f.python_requires)
                claims.append(self._at(self._ok("VERSION", v.group(0), ok, why), doc, sentence, located.line))
            for v in re.finditer(r"\b([A-Za-z][\w.-]+)\s+v?(\d+\.\d+(?:\.\d+)?)\b", plain):
                dep = v.group(1).lower()
                if dep != "python" and (dep in self.f.dependencies or dep in {t.lower() for t in TECH}):
                    ok, why = version_ok(v.group(2), self.f.dependencies.get(dep))
                    claims.append(self._at(self._ok("VERSION", v.group(0), ok, why), doc, sentence, located.line))
        return claims

    @staticmethod
    def _at(c: Claim, doc: str, sentence: str, line: int) -> Claim:
        c.doc, c.sentence, c.line = doc, sentence.strip()[:400], line
        return c


def sentences(text: str) -> list[Located]:
    """Sentences with their line; a table row, list item or heading is its own sentence."""
    out: list[Located] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or set(line) <= set("|-: "):
            continue
        if line.startswith("|"):
            out.append(Located(line, n))
            continue
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z`(\"])", line):
            if part.strip():
                out.append(Located(part.strip(), n))
    return out


def joined_lines(block: str) -> list[tuple[int, str]]:
    """Command lines of a shell block, with ``\\`` continuations joined (line index of the first part)."""
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for i, line in enumerate(block.splitlines()):
        if not buf:
            start = i
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append((start, buf + line))
        buf = ""
    if buf:
        out.append((start, buf))
    return out

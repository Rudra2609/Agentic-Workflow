"""README generator (Sprint 9 item 9.4, plan D6; from the prototype's ``draft_readme.py``).

Fixed sections, every technical line filled from the facts, so they are grounded by construction:

    What (model prose, checked like everything else) · Run · Configuration · Endpoints · Architecture · Code · Tests

The model writes only the "What" paragraph, from the facts it is given; without a model it is a facts-only
sentence (plan D14). Large repositories get capped tables with a pointer to the API / configuration documents.
"""

import re

from pydantic import BaseModel, Field

from hmap.agents.docgen.architecture import Architecture, code_modules, mermaid
from hmap.agents.docgen.model import Facts
from hmap.agents.docgen.summarize import UNTRUSTED, Summaries, facts_overview, quote
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.docgen.readme")

MAX_ENV_ROWS = 25
MAX_ROUTE_ROWS = 25
RUN_TARGETS = ("demo", "demo-replay", "run", "start", "dev", "api", "agents", "test", "check", "stop")
LONG_RUNNING = ("socket", "uvicorn", "flask", "http.server", "socketserver", "aiohttp")


class _Prose(BaseModel):
    what: str = Field(max_length=900)


def install_commands(facts: Facts) -> list[str]:
    names = {f.rsplit("/", 1)[-1] for f in facts.files if "/" not in f}
    out = []
    if "uv.lock" in names:
        out.append("uv sync")
    elif "pyproject.toml" in names:
        out.append('pip install -e ".[' + ",".join(facts.extras) + ']"' if facts.extras else "pip install -e .")
    elif "requirements.txt" in names:
        out.append("pip install -r requirements.txt")
    if "package.json" in names:
        out.append("npm ci")
    return out


def run_commands(facts: Facts) -> list[str]:
    """Make targets and console scripts first (how the project is meant to be run), then entry points."""
    out = [f"make {t}" for t in RUN_TARGETS if t in facts.make_targets][:6]
    out += [script for script in sorted(facts.scripts) if not script.startswith("npm run ")][:4]
    out += [s for s in ("npm run dev", "npm run build", "npm start") if s in facts.scripts][:2]
    modules = 0
    code = code_modules(facts)
    for entry in facts.entrypoints:
        if not entry.endswith(".py") or entry not in code or ("/" in entry and entry.split("/")[0] == "scripts"):
            continue
        mod = facts.modules.get(entry)
        if mod is not None and "." in mod.module:                 # inside a package: run it as a module
            if modules < 3 and len(out) < 6:                      # a few, after the make targets
                out.append(f"python -m {mod.module}")
                modules += 1
            continue
        if mod is not None and mod.path in facts.subcommands:     # argparse sub-commands: show the help
            out.append(f"python {entry} --help")
            continue
        required = facts.cli_required.get(entry, [])
        out.append(f"python {entry}" + "".join(f" {flag} VALUE" for flag in required))
    return out[:12]


def test_commands(facts: Facts) -> list[str]:
    out = []
    if facts.tests and facts.language == "python":
        out.append("pytest")
    if "npm run test" in facts.scripts:
        out.append("npm run test")
    return out


def long_running(facts: Facts, path: str) -> bool:
    mod = facts.modules.get(path)
    return bool(mod and (set(mod.imports) & set(LONG_RUNNING) or any(r.file == path for r in facts.routes)))


def sections(facts: Facts, arch: Architecture, summaries: Summaries | None) -> list[str]:
    out: list[str] = []
    if facts.python_requires:
        spec = facts.python_requires
        out += [f"Requires Python {re.sub(r'^[<>=~! ]+', '', spec).split(',')[0]} (`requires-python {spec}`).", ""]
    install, run = install_commands(facts), run_commands(facts)
    if install or run:
        out += ["## Run", "```bash", *install, *run, "```", ""]
    code = code_modules(facts)
    for script, flags in sorted(facts.cli.items()):
        if flags and script in code:
            out += [f"`{script}` options: " + ", ".join(f"`{f}`" + (f" ({' / '.join(c)})" if c else "")
                                                         for f, c in sorted(flags.items())), ""]
    if facts.env:
        rows = list(facts.env.items())
        out += ["## Configuration", "", "| Variable | Default |", "|---|---|"]
        out += [f"| `{name}` | {default if default not in (None, '') else '(not set)'} |"
                for name, default in rows[:MAX_ENV_ROWS]]
        if len(rows) > MAX_ENV_ROWS:
            out += ["", f"… and {len(rows) - MAX_ENV_ROWS} more environment variables (see the configuration "
                        "reference)."]
        out.append("")
    if facts.ports:
        out += ["Listens on " + " and ".join(f"port {p}" for p in facts.ports[:4]) + ".", ""]
    if facts.routes:
        out += ["## Endpoints", "", "| Endpoint | Defined in |", "|---|---|"]
        out += [f"| {r.method} {r.path} | `{r.file}` |" for r in facts.routes[:MAX_ROUTE_ROWS]]
        if len(facts.routes) > MAX_ROUTE_ROWS:
            out += ["", f"… {len(facts.routes) - MAX_ROUTE_ROWS} more in [the API reference](api.md)."]
        out.append("")
    out += ["## Architecture", "", "```mermaid", mermaid(arch, externals=len(arch.components) <= 12).rstrip(), "```",
            "", "More: [architecture](architecture.md).", ""]
    out += ["## Code", ""]
    described = {s.path: s for s in (summaries.symbols if summaries else [])}
    for path, mod in list(code_modules(facts).items())[:40]:
        names = [f"`{f}()`" for f in mod.functions if not f.startswith("_")][:6]
        about = summaries.files.get(path, "") if summaries else ""
        if about and summaries and summaries.file_by.get(path) == "docstring":
            about = quote(about)
        line = f"- `{path}`" + (f": {about}" if about else (": " + ", ".join(names) if names else ""))
        if not about and path in described:
            line = f"- `{path}`: " + ", ".join(names)
        out.append(line)
    if len(code_modules(facts)) > 40:
        out.append(f"- … {len(code_modules(facts)) - 40} more modules (see the code summaries).")
    tests = test_commands(facts)
    if facts.tests or tests:
        out += ["", "## Tests", ""]
        if tests:
            out += ["```bash", *tests, "```"]
        shown = ", ".join(f"`{t}`" for t in facts.tests[:8])
        more = f" and {len(facts.tests) - 8} more" if len(facts.tests) > 8 else ""
        out.append(f"{len(facts.tests)} test file(s) with {facts.test_functions} test functions: {shown}{more}.")
    return out


async def what_paragraph(llm: LLMClient | None, facts: Facts, summaries: Summaries | None,
                         arch: Architecture) -> tuple[str, int, int]:
    base = summaries.repo if summaries and summaries.repo_by == "model" else facts_overview(facts, arch)
    if llm is None:
        return base, 0, 0
    deps = ", ".join(sorted(facts.dependencies)[:30]) or "only the standard library"
    prompt = (f"Repository: {facts.repo}\nWhat the code contains: {facts_overview(facts, arch)}\n"
              f"Summary of the code: {summaries.repo if summaries else ''}\nDeclared dependencies: {deps}\n"
              f"Entry points: {', '.join(facts.entrypoints) or 'none'}\n\nWrite the opening paragraph of the "
              "README (2-4 sentences): what the project does and for whom. Use only these facts; do not name any "
              "technology, command, port or file that is not listed above.")
    try:
        resp = await llm.generate("reasoner", [{"role": "system", "content": "You write README files. " + UNTRUSTED},
                                               {"role": "user", "content": prompt}],
                                  schema=_Prose, max_tokens=500, temperature=0.0, seed=7)
    except Exception as exc:
        log.info("README prose skipped", error=type(exc).__name__)
        return base, 0, 0
    parsed = resp.parsed if isinstance(resp.parsed, _Prose) else None
    text = " ".join(parsed.what.split()) if parsed and parsed.what.strip() else base
    return text, 1, resp.usage.input_tokens + resp.usage.output_tokens


def render(facts: Facts, arch: Architecture, summaries: Summaries | None, what: str) -> str:
    return "\n".join([f"# {facts.repo}", "", what, "", *sections(facts, arch, summaries)]).rstrip() + "\n"

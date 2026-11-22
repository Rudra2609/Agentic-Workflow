"""Configuration reference (Sprint 9 item 9.17, plan P5), generated from the code: every environment variable that
``Settings.from_env`` reads, its type, default and description (the field's ``description``, else the comment in
``.env.example``), grouped like ``.env.example``.

    uv run python -m hmap.agents.docgen.config_reference          # -> docs/members/9/platform/configuration.md

:func:`drift` is the check behind the test: a variable the code reads but ``.env.example`` does not list (or the
other way round) is drift. Keys are never printed: secret fields show "(secret)".
"""

import ast
import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from hmap.core import config
from hmap.core.config import REPO_ROOT, Settings

OUT = REPO_ROOT / "docs" / "members" / "9" / "platform" / "configuration.md"
# read from the process environment before (or instead of) .env, so they cannot be set in it
PROCESS_ONLY = {"HMAP_ENV_FILE": "which env file to read instead of the repository's .env",
                "HMAP_ROOT": "the repository root (default: found from the code's location)",
                "HMAP_RUN_AGENTS": "false = the API process runs no agents (make demo runs them in their own process)"}
SECRET = re.compile(r"_(KEYS?|SECRETS?|PASSWORD|TOKEN)$")


@dataclass
class Var:
    name: str
    field: str | None
    type: str
    default: str
    description: str
    group: str


def env_vars_in_code() -> dict[str, str | None]:
    """Every ``HMAP_*`` / ``OLLAMA_*`` string the settings loader reads, mapped to its field (from the AST of
    ``from_env``: the mapping dict, the ``(name, field)`` pairs and the ``get("X")`` calls)."""
    tree = ast.parse(inspect.getsource(config))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "from_env")
    out: dict[str, str | None] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=False):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and re.fullmatch(r"[A-Z][A-Z0-9_]+", k.value):
                    out[k.value] = v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else None
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2 and all(isinstance(e, ast.Constant)
                                                                         for e in node.elts):
            a, b = (e.value for e in node.elts)  # type: ignore[attr-defined]
            if isinstance(a, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", a) and isinstance(b, str):
                out[a] = b
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "get" and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            name = node.args[0].value
            if re.fullmatch(r"[A-Z][A-Z0-9_]+", name):
                out.setdefault(name, name.removeprefix("HMAP_").lower())
    return dict(sorted(out.items()))


def env_example(path: Path = REPO_ROOT / ".env.example") -> dict[str, tuple[str, str, str]]:
    """name -> (value, comment, group heading) as written in ``.env.example`` (commented-out lines too)."""
    out: dict[str, tuple[str, str, str]] = {}
    group = "General"
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^#\s*-{2,}\s*(.+?)\s*-*\s*$", line):
            group = m.group(1).strip(" -")
            continue
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=([^#]*?)\s*(?:#\s*(.*))?$", line)
        if m:
            out.setdefault(m.group(1), (m.group(2).strip(), (m.group(3) or "").strip(), group))
    return out


def _type(annotation: Any) -> str:
    text = getattr(annotation, "__name__", None) or str(annotation)
    return text.replace("typing.", "").replace("pathlib.", "").replace("hmap.core.llm.base.", "")


def variables() -> list[Var]:
    code = env_vars_in_code()
    example = env_example()
    fields = Settings.model_fields
    out = []
    for name in sorted(set(code) | set(example)):
        field = code.get(name)
        f = fields.get(field) if field else None
        value, comment, group = example.get(name, ("", "", "not in .env.example"))
        if f is not None:
            default: Any = f.get_default(call_default_factory=True)
            secret = f.annotation is SecretStr or "SecretStr" in str(f.annotation) or SECRET.search(name)
            shown = "(secret)" if secret and default not in (None, "", []) else str(default) if default not in (
                None, "", [], ()) else "(not set)"
            if isinstance(default, Path):
                shown = default.relative_to(REPO_ROOT).as_posix() if default.is_relative_to(REPO_ROOT) else str(default)
            out.append(Var(name, field, _type(f.annotation), shown, f.description or comment, group))
        else:
            out.append(Var(name, field, "", "(secret)" if SECRET.search(name) and value else value or "(not set)",
                           comment, group))
    return out


def env_vars_elsewhere() -> set[str]:
    """Read outside the settings loader: ``os.environ`` in the backend (the facts extractor) and ``${HMAP_X}`` in the
    compose files."""
    from hmap.agents.docgen.inspect import inspect_files, read_tree

    names = {n for n in inspect_files(read_tree(REPO_ROOT / "backend" / "src"), "src").env if n.startswith("HMAP_")}
    for f in (REPO_ROOT / "infra").glob("*.yml"):
        names |= set(re.findall(r"\$\{(HMAP_[A-Z0-9_]+)", f.read_text(encoding="utf-8")))
    return names


def drift() -> dict[str, list[str]]:
    code, example = set(env_vars_in_code()) | env_vars_elsewhere(), set(env_example())
    hmap = {n for n in code if n.startswith("HMAP_")}
    return {"read_by_code_not_in_env_example": sorted(hmap - example - set(PROCESS_ONLY)),
            "in_env_example_not_read": sorted(n for n in example - code if n.startswith("HMAP_"))}


def render() -> str:
    rows: dict[str, list[Var]] = {}
    for v in variables():
        rows.setdefault(v.group, []).append(v)
    lines = ["# Configuration reference", "",
             "Generated from the code (`Settings.from_env` in `backend/src/hmap/core/config.py`) and the comments in "
             "`.env.example` by `uv run python -m hmap.agents.docgen.config_reference`. Do not edit by hand. Set a "
             "value in `.env` (git-ignored) or the environment; the environment wins. Keys live only in `.env`.", ""]
    d = drift()
    for group, vs in rows.items():
        lines += [f"## {group}", "", "| Variable | Type | Default | What it does |", "|---|---|---|---|"]
        for v in vs:
            desc = v.description.replace("|", "/")
            lines.append(f"| `{v.name}` | {v.type.replace('|', '/')} | {str(v.default).replace('|', '/')} | {desc} |")
        lines.append("")
    lines += ["## Process environment only", "",
              "Read before `.env` is loaded: set them in the shell, not in `.env`.", "",
              "| Variable | What it does |", "|---|---|"]
    lines += [f"| `{k}` | {v} |" for k, v in PROCESS_ONLY.items()]
    lines.append("")
    if any(d.values()):
        lines += ["## Drift", "",
                  f"- read by the code but not in `.env.example`: {d['read_by_code_not_in_env_example']}",
                  f"- in `.env.example` but not read: {d['in_env_example_not_read']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    print(f"wrote {out}: {len(variables())} variables; drift: {drift()}")


if __name__ == "__main__":
    main()

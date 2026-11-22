"""Facts extractor (Sprint 9 item 9.1, plan D3): everything a repository really contains, from the files alone.

    facts = inspect_files({"server.py": "...", "requirements.txt": "..."}, repo="tcp_chat")
    facts = inspect_files(read_tree(Path("backend")), repo="backend")       # a folder on disk (dogfood)

No model, nothing imported or run; well under a second for the platform's own backend. The facts are the only
thing generated documentation may claim (``grounding``), and every generator fills its sections from them.
"""

import re
from pathlib import Path

from hmap.agents.docgen.inspect import javascript
from hmap.agents.docgen.inspect.manifests import read_manifest
from hmap.agents.docgen.inspect.python import module_facts, module_name
from hmap.agents.docgen.model import Facts, Route, is_test_path

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             ".next", "dist", "build", ".tmp", ".hypothesis", "htmlcov", ".idea", ".vscode"}
MAX_FILES = 5000
MAX_FILE_BYTES = 400_000
TEXT_SUFFIXES = {".py", ".txt", ".toml", ".json", ".md", ".cfg", ".ini", ".yml", ".yaml", ".sh", ".js", ".mjs",
                 ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".sql", ".env", ".example", ".mmd", ".csv"}
TEXT_NAMES = {"Makefile", "Dockerfile", "Procfile", ".gitignore", ".env.example"}


def read_tree(root: Path, *, max_files: int = MAX_FILES) -> dict[str, str]:
    """Text files under ``root`` (repo-relative POSIX paths), skipping caches, virtualenvs and ``.env`` files."""
    root = root.resolve()
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if SKIP_DIRS & set(rel_parts[:-1]) or not path.is_file() or path.is_symlink():
            continue
        name = path.name
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            continue                                     # never read secrets (project rule: keys live only in .env)
        if path.suffix not in TEXT_SUFFIXES and name not in TEXT_NAMES and not name.startswith("Dockerfile"):
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            out["/".join(rel_parts)] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if len(out) >= max_files:
            break
    return out


def inspect_files(files: dict[str, str], repo: str = "repo", listing: list[str] | None = None) -> Facts:
    """``listing``: other paths of the repository, names only (they exist; their contents are not facts)."""
    facts = Facts(repo=repo, files=sorted({*files, *(listing or [])}))
    py = sorted(p for p in files if p.endswith(".py"))
    packages = {p.rsplit("/", 1)[0] for p in py if p.endswith("/__init__.py")}
    names = {module_name(p, packages): p for p in py}
    owners: list[tuple[str, Route]] = []
    routers: dict[tuple[str, str], str] = {}
    includes: list[tuple[str, str, str]] = []
    for rel in py:
        mod, bits = module_facts(rel, module_name(rel, packages), files[rel], names)
        facts.modules[rel] = mod
        if mod.error:
            facts.notes.append(f"{rel}: {mod.error}")
        for route in bits.routes:
            owner, _, fn = route.function.partition("|")
            route.function = fn
            owners.append((owner, route))
        routers.update({(rel, var): prefix for var, prefix in bits.routers.items()})
        includes += [(rel, expr, prefix) for expr, prefix in bits.includes]
        if bits.cli:
            facts.cli.setdefault(rel, {}).update(bits.cli)
        if bits.required:
            facts.cli_required[rel] = sorted(set(bits.required))
        for k, v in bits.env.items():
            facts.env.setdefault(k, v)
        facts.ports += bits.ports
        facts.file_literals += bits.file_literals
        facts.test_functions += bits.test_functions
        if is_test_path(rel) and rel.rsplit("/", 1)[-1].startswith("test"):
            facts.tests.append(rel)
        if mod.main:
            facts.entrypoints.append(rel)
        if "add_subparsers(" in files[rel]:
            facts.subcommands.append(rel)
    names_set = set(files)
    for rel in sorted(p for p in files if javascript.is_js(p) and "node_modules/" not in p):
        mod, bits = javascript.module_facts(rel, files[rel], names_set)
        facts.modules[rel] = mod
        owners += [("", r) for r in bits.routes]
        for k, v in bits.env.items():
            facts.env.setdefault(k, v)
        facts.ports += bits.ports
        facts.test_functions += bits.test_functions
        if javascript.is_js_test(rel):
            facts.tests.append(rel)
    facts.routes = _apply_prefixes(owners, routers, includes, facts)
    for rel in sorted(files):
        if not rel.endswith(".py"):
            read_manifest(rel, files[rel], facts)
    for target in facts.scripts.values():               # [project.scripts] hmap-agents = "hmap.x:main"
        script_path = names.get(target.split(":", 1)[0])
        if script_path and script_path not in facts.entrypoints:
            facts.entrypoints.append(script_path)
    facts.ports = sorted(set(facts.ports))
    facts.file_literals = sorted(set(facts.file_literals))
    facts.technologies = sorted(set(facts.technologies))
    facts.services = sorted(set(facts.services))
    facts.make_targets = sorted(set(facts.make_targets))
    facts.entrypoints = sorted(set(facts.entrypoints))
    facts.env = dict(sorted(facts.env.items()))
    facts.dependencies = dict(sorted(facts.dependencies.items()))
    js = [p for p in files if javascript.is_js(p)]
    if js and not py:
        facts.language = "javascript"
    if js:
        facts.technologies = sorted({*facts.technologies, "javascript"})
    return facts


def _apply_prefixes(owners: list[tuple[str, Route]], routers: dict[tuple[str, str], str],
                    includes: list[tuple[str, str, str]], facts: Facts) -> list[Route]:
    """``APIRouter(prefix="/todos")`` on the router's variable, then ``include_router(x.router, prefix="/api")``
    when the included expression names a module of this repository (``projects.router`` or ``router``)."""
    by_module = {m.module.rsplit(".", 1)[-1]: path for path, m in facts.modules.items()}
    outer: dict[str, str] = {}
    for rel, expr, prefix in includes:
        target = expr.split(".")[0] if "." in expr else None
        path = by_module.get(target) if target else None
        if path is None and target is None:
            for imported in facts.modules[rel].local_imports:     # from .routers.todos import router
                if (imported, expr) in routers:
                    path = imported
        if path:
            outer[path] = prefix
    out = []
    for owner, route in owners:
        prefix = routers.get((route.file, owner), "")
        full = (outer.get(route.file, "") + prefix + route.path) or "/"
        route.path = re.sub(r"//+", "/", full)
        out.append(route)
    return sorted(out, key=lambda r: (r.path, r.method))


__all__ = ["inspect_files", "read_tree"]

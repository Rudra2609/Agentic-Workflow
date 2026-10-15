#!/usr/bin/env python3
"""Facts extractor for a Python repository (Member 9, prepared ahead of Sprint 9 items 9.1 / 9.2). Reads the code
with ``ast`` (nothing is imported or run) and the manifests, and writes what the repository really contains: files,
modules, functions and classes, imported libraries, declared dependencies, HTTP routes (FastAPI / Flask), command-line
flags (argparse), environment variables, ports, entry points and tests. Also draws the local import graph as Mermaid.
Plain Python 3.11, no project code.

    python3 samples/docgen/inspect_repo.py samples/docgen/repos/todo_api          # prints facts.json
    python3 samples/docgen/inspect_repo.py <repo> --mermaid                        # prints the component diagram

These facts are the only thing generated documentation is allowed to claim (see ``grounding.py``).
"""

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}


def _const(node: ast.AST | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _int(node: ast.AST | None) -> int | None:
    """An int literal, or ``int("5050")`` / ``int(os.getenv("X", "5050"))`` style defaults."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "int" and node.args:
        inner = node.args[0]
        if isinstance(inner, ast.Constant) and str(inner.value).isdigit():
            return int(inner.value)
        if isinstance(inner, ast.Call) and len(inner.args) > 1 and str(_const(inner.args[1])).isdigit():
            return int(_const(inner.args[1]))
    return None


def _env_call(node: ast.AST) -> tuple[str, object] | None:
    """``os.environ.get("X", d)``, ``os.getenv("X", d)`` or ``os.environ["X"]`` -> ("X", d)."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
        f = node.func
        is_getenv = f.attr == "getenv"
        is_environ_get = f.attr == "get" and isinstance(f.value, ast.Attribute) and f.value.attr == "environ"
        if (is_getenv or is_environ_get) and isinstance(_const(node.args[0]), str):
            return node.args[0].value, _const(node.args[1]) if len(node.args) > 1 else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "environ":
        if isinstance(_const(node.slice), str):
            return node.slice.value, None
    return None


def _requirement_name(spec: str) -> tuple[str, str]:
    m = re.match(r"\s*([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)", spec)
    return (m.group(1).lower().replace("_", "-"), m.group(3).strip()) if m else (spec.strip().lower(), "")


def _module_facts(rel: str, tree: ast.Module, facts: dict) -> None:
    mod = {"functions": [], "classes": [], "imports": [], "main": False}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            mod["functions"].append(node.name)
            for dec in node.decorator_list:  # @app.get("/x"), @router.post("/x"), @app.route("/x", methods=[...])
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                    path = _const(dec.args[0])
                    if not isinstance(path, str) or not path.startswith("/"):
                        continue
                    if dec.func.attr in HTTP_METHODS:
                        facts["routes"].append({"method": dec.func.attr.upper(), "path": path, "file": rel})
                    elif dec.func.attr == "route":
                        methods = next((kw.value for kw in dec.keywords if kw.arg == "methods"), None)
                        names = [_const(e) for e in methods.elts] if isinstance(methods, ast.List) else ["GET"]
                        facts["routes"] += [{"method": m.upper(), "path": path, "file": rel} for m in names]
        elif isinstance(node, ast.ClassDef):
            mod["classes"].append(node.name)
        elif isinstance(node, ast.Import):
            mod["imports"] += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mod["imports"].append(node.module.split(".")[0])
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if getattr(node.test.left, "id", None) == "__name__" and _const(node.test.comparators[0]) == "__main__":
                mod["main"] = True
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if "PORT" in node.targets[0].id.upper() and (port := _int(node.value)) is not None:
                facts["ports"].append(port)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"[\w.\-/]+\.\w{1,5}",
                                                                                               node.value):
            facts["file_literals"].append(node.value)  # file names the code itself uses ("todos.db")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument" and node.args:
                flags = [_const(a) for a in node.args if str(_const(a)).startswith("-")]
                kw = {k.arg: k.value for k in node.keywords}
                choices = [_const(e) for e in kw["choices"].elts] if isinstance(kw.get("choices"), ast.List) else None
                for flag in flags:
                    facts["cli"].setdefault(rel, {})[flag] = choices
                if "--port" in flags and (port := _int(kw.get("default"))) is not None:
                    facts["ports"].append(port)
            for k in node.keywords:  # uvicorn.run(..., port=8000), app.run(port=5001)
                if k.arg == "port" and (port := _int(k.value)) is not None:
                    facts["ports"].append(port)
        if env := _env_call(node):
            facts["env"].setdefault(env[0], env[1])
            if "PORT" in env[0] and str(env[1]).isdigit():
                facts["ports"].append(int(env[1]))
    facts["modules"][rel] = mod


def inspect(repo: Path) -> dict:
    repo = repo.resolve()
    facts: dict = {"repo": repo.name, "files": [], "modules": {}, "dependencies": {}, "extras": [],
                   "python_requires": None, "routes": [], "cli": {}, "env": {}, "ports": [], "tests": [],
                   "entrypoints": [], "file_literals": []}
    for path in sorted(repo.rglob("*")):
        if path.is_dir() or SKIP_DIRS & set(path.relative_to(repo).parts):
            continue
        rel = path.relative_to(repo).as_posix()
        facts["files"].append(rel)
        if path.suffix == ".py":
            _module_facts(rel, ast.parse(path.read_text(encoding="utf-8"), rel), facts)
            if path.name.startswith("test_"):
                facts["tests"].append(rel)
            if facts["modules"][rel]["main"]:
                facts["entrypoints"].append(rel)
        elif path.name.startswith("requirements") and path.suffix == ".txt":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith(("#", "-")):
                    name, spec = _requirement_name(line)
                    facts["dependencies"][name] = spec
        elif path.name == "pyproject.toml":
            project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
            facts["python_requires"] = project.get("requires-python")
            groups = project.get("optional-dependencies", {})
            facts["extras"] = sorted(groups)
            for spec in project.get("dependencies", []) + [s for g in groups.values() for s in g]:
                name, version = _requirement_name(spec)
                facts["dependencies"][name] = version
    facts["ports"] = sorted(set(facts["ports"]))
    facts["file_literals"] = sorted(set(facts["file_literals"]))
    return facts


def import_graph(facts: dict) -> list[tuple[str, str]]:
    """Edges between the repository's own modules (``server.py`` imports ``protocol``)."""
    local = {Path(rel).stem: rel for rel in facts["modules"]}
    return sorted({(rel, local[name]) for rel, mod in facts["modules"].items()
                   for name in mod["imports"] if name in local and local[name] != rel})


def mermaid(facts: dict) -> str:
    def node(rel: str) -> str:
        return re.sub(r"\W", "_", rel.removesuffix(".py"))

    lines = ["flowchart LR"]
    external = sorted({name for mod in facts["modules"].values() for name in mod["imports"]}
                      & {d.replace("-", "_") for d in facts["dependencies"]})
    for rel in facts["modules"]:
        shape = f'{node(rel)}(["{rel}"])' if rel in facts["entrypoints"] else f'{node(rel)}["{rel}"]'
        lines.append(f"  {shape}")
    for a, b in import_graph(facts):
        lines.append(f"  {node(a)} --> {node(b)}")
    for lib in external:
        lines.append(f"  lib_{lib}[(\"{lib}\")]")
        lines += [f"  {node(rel)} -.-> lib_{lib}" for rel, mod in facts["modules"].items() if lib in mod["imports"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    found = inspect(Path(sys.argv[1]))
    print(mermaid(found) if "--mermaid" in sys.argv else json.dumps(found, indent=1))

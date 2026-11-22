"""Python facts from the AST (Sprint 9 item 9.1, ported from ``samples/docgen/inspect_repo.py``). Nothing is
imported or run: the code may be a model's output (plan T4).

Per module: symbols with signatures and docstrings, imports, ``__main__``; for the repository: HTTP routes (FastAPI
``@app.get`` / ``APIRouter(prefix=)`` / ``include_router(prefix=)``, Flask ``@app.route``), command-line flags
(argparse ``add_argument``, click ``@click.option``), environment variables (``os.environ`` / ``getenv`` /
``environ.get``, settings tables like ``{"HMAP_BUS": "bus"}`` or ``("HMAP_X", "x")`` pairs, ``get("HMAP_X")``,
pydantic ``BaseSettings`` + ``env_prefix``), ports and the file names the code itself uses.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.docgen.model import ModuleFacts, Route, Symbol

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
ENV_NAME = re.compile(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+")
FILE_LITERAL = re.compile(r"[\w.\-/]+\.(db|sqlite3?|json|ya?ml|toml|txt|csv|md|html|log|cfg|ini|env|sql|xml)")
SKIP_PARAMS = {"self", "cls", "request", "response", "background_tasks"}


def _const(node: ast.AST | None) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _int(node: ast.AST | None) -> int | None:
    """An int literal, or ``int("5050")`` / ``int(os.getenv("X", "5050"))`` style defaults."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "int" and node.args:
        inner = node.args[0]
        if isinstance(inner, ast.Constant) and str(inner.value).isdigit():
            return int(str(inner.value))
        if isinstance(inner, ast.Call) and len(inner.args) > 1 and str(_const(inner.args[1])).isdigit():
            return int(str(_const(inner.args[1])))
    return None


def _port(value: int | None) -> int | None:
    return value if value is not None and 1 <= value <= 65535 else None


def _env_call(node: ast.AST) -> tuple[str, object] | None:
    """``os.environ.get("X", d)``, ``os.getenv("X", d)``, ``os.environ["X"]``, ``get("HMAP_X")`` -> ("X", d)."""
    if isinstance(node, ast.Call) and node.args and isinstance(_const(node.args[0]), str):
        name = str(_const(node.args[0]))
        default = _const(node.args[1]) if len(node.args) > 1 else None
        f = node.func
        if isinstance(f, ast.Attribute) and (f.attr == "getenv" or (
                f.attr in ("get", "pop", "setdefault") and isinstance(f.value, ast.Attribute)
                and f.value.attr == "environ")):
            return name, default
        if isinstance(f, ast.Name) and f.id in ("getenv", "get", "env") and ENV_NAME.fullmatch(name):
            return name, default
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "environ" \
            and isinstance(_const(node.slice), str):
        return str(_const(node.slice)), None
    return None


def _first(doc: str | None, limit: int = 600) -> str:
    return (doc or "").strip()[:limit]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'} {node.name}({args}){ret}"


def _public(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__") and name == "__init__")


@dataclass
class RepoBits:
    """What a module adds to the repository-wide facts (merged by ``inspect.inspect_files``)."""

    routes: list[Route] = field(default_factory=list)
    routers: dict[str, str] = field(default_factory=dict)            # variable -> APIRouter(prefix=...)
    includes: list[tuple[str, str]] = field(default_factory=list)    # (router expression, prefix)
    cli: dict[str, list[str] | None] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    env: dict[str, str | None] = field(default_factory=dict)
    ports: list[int] = field(default_factory=list)
    file_literals: list[str] = field(default_factory=list)
    test_functions: int = 0


def _route_params(node: ast.FunctionDef | ast.AsyncFunctionDef, classes: set[str]) -> tuple[list[str], str | None]:
    params, body = [], None
    for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
        if a.arg in SKIP_PARAMS:
            continue
        ann = ast.unparse(a.annotation) if a.annotation is not None else ""
        if "Depends" in ann or "Request" in ann:
            continue
        params.append(f"{a.arg}: {ann}" if ann else a.arg)
        if body is None and ann in classes:
            body = ann
    return params, body


def _routes_of(node: ast.FunctionDef | ast.AsyncFunctionDef, rel: str, classes: set[str]) -> list[Route]:
    out: list[Route] = []
    for dec in node.decorator_list:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args):
            continue
        path = _const(dec.args[0])
        if not isinstance(path, str) or not (path.startswith("/") or path == ""):
            continue
        owner = ast.unparse(dec.func.value)
        kw = {k.arg: k.value for k in dec.keywords if k.arg}
        params, body = _route_params(node, classes)
        response = ast.unparse(kw["response_model"]) if "response_model" in kw else None
        base: dict[str, Any] = dict(path=path, file=rel, function=node.name, line=node.lineno, params=params, body=body,
                    response_model=response, doc=_first(ast.get_docstring(node), 300))
        if dec.func.attr in HTTP_METHODS:
            out.append(Route(method=dec.func.attr.upper(), **base))
            out[-1].function = f"{owner}|{node.name}"
        elif dec.func.attr in ("route", "api_route"):
            methods = kw.get("methods")
            names = [str(_const(e)) for e in methods.elts] if isinstance(methods, ast.List | ast.Tuple) else ["GET"]
            for m in names:
                out.append(Route(method=m.upper(), **base))
                out[-1].function = f"{owner}|{node.name}"
    return out


def module_facts(rel: str, module: str, text: str, local_names: dict[str, str]) -> tuple[ModuleFacts, RepoBits]:
    """Facts of one Python file. ``local_names``: dotted module name -> path of every module in the repository."""
    mod = ModuleFacts(path=rel, module=module, lines=text.count("\n") + (0 if text.endswith("\n") else 1))
    bits = RepoBits()
    try:
        tree = ast.parse(text, rel)
    except SyntaxError as exc:
        mod.error = f"SyntaxError line {exc.lineno}"
        return mod, bits
    mod.doc = _first(ast.get_docstring(tree))
    classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    is_test = rel.rsplit("/", 1)[-1].startswith("test_") or "/tests/" in f"/{rel}"
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            mod.classes.append(node.name)
            mod.symbols.append(Symbol(name=node.name, kind="class", line=node.lineno,
                                      signature=f"class {node.name}" + (
                                          f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""),
                                      doc=_first(ast.get_docstring(node)), public=_public(node.name)))
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    mod.symbols.append(Symbol(name=sub.name, kind="method", line=sub.lineno, parent=node.name,
                                              signature=_signature(sub), doc=_first(ast.get_docstring(sub)),
                                              public=_public(sub.name) and _public(node.name)))
            _settings_env(node, bits)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            mod.functions.append(node.name)
            mod.symbols.append(Symbol(name=node.name, kind="function", line=node.lineno, signature=_signature(node),
                                      doc=_first(ast.get_docstring(node)), public=_public(node.name)))
    for node in ast.walk(tree):  # type: ignore[assignment]
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name not in mod.functions and node.col_offset == 0:
                mod.functions.append(node.name)
            bits.routes += _routes_of(node, rel, classes)
            if is_test and node.name.startswith("test"):
                bits.test_functions += 1
            for dec in node.decorator_list:      # click: @click.option("--name", type=click.Choice([...]))
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "option":
                    _flag(bits, dec)
        elif isinstance(node, ast.Import):
            for a in node.names:
                mod.imports.append(a.name.split(".")[0])
                mod.imported_names.append(a.asname or a.name.split(".")[0])
                _local(mod, a.name, local_names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(module, node.module, node.level, rel)
            if node.level == 0 and node.module:
                mod.imports.append(node.module.split(".")[0])
            mod.imported_names += [a.asname or a.name for a in node.names if a.name != "*"]
            if base:
                for a in node.names:
                    if not _local(mod, f"{base}.{a.name}", local_names):
                        _local(mod, base, local_names)
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            if getattr(node.test.left, "id", None) == "__name__" and node.test.comparators \
                    and _const(node.test.comparators[0]) == "__main__":
                mod.main = True
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if target.isupper() and node.col_offset == 0:
                mod.constants.append(target)
            if "PORT" in target.upper() and (port := _port(_int(node.value))) is not None:
                bits.ports.append(port)
            if isinstance(node.value, ast.Call) and getattr(node.value.func, "id", getattr(node.value.func, "attr",
                                                                                         "")) == "APIRouter":
                prefix = next((_const(k.value) for k in node.value.keywords if k.arg == "prefix"), "")
                bits.routers[target] = str(prefix or "")
        elif isinstance(node, ast.Dict) and len(node.keys) >= 3:
            keys = [_const(k) for k in node.keys]
            if all(isinstance(k, str) and ENV_NAME.fullmatch(k) for k in keys):    # {"HMAP_BUS": "bus", ...}
                for k in keys:
                    bits.env.setdefault(str(k), None)
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2 and all(isinstance(_const(e), str)
                                                                         for e in node.elts):
            first = str(_const(node.elts[0]))
            second = str(_const(node.elts[1]))
            if ENV_NAME.fullmatch(first) and re.fullmatch(r"[a-z_][a-z0-9_]*", second):   # ("HMAP_X", "x")
                bits.env.setdefault(first, None)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and FILE_LITERAL.fullmatch(node.value):
            bits.file_literals.append(node.value)
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "add_argument" and node.args:
                _flag(bits, node)
            if isinstance(f, ast.Attribute) and f.attr == "include_router" and node.args:
                prefix = next((_const(k.value) for k in node.keywords if k.arg == "prefix"), "")
                bits.includes.append((ast.unparse(node.args[0]), str(prefix or "")))
            for k in node.keywords:              # uvicorn.run(..., port=8000), app.run(port=5001)
                if k.arg == "port" and (port := _port(_int(k.value))) is not None:
                    bits.ports.append(port)
            if isinstance(f, ast.Attribute) and f.attr in ("bind", "connect", "create_connection") and node.args:
                addr = node.args[0]                  # sock.bind(("127.0.0.1", 5050))
                if isinstance(addr, ast.Tuple) and len(addr.elts) == 2 and (port := _port(_int(addr.elts[1]))):
                    bits.ports.append(port)
        if env := _env_call(node):
            bits.env.setdefault(env[0], None if env[1] is None else str(env[1]))
            if "PORT" in env[0] and str(env[1]).isdigit() and (port := _port(int(str(env[1])))):
                bits.ports.append(port)
    mod.imports = sorted(set(mod.imports))
    mod.imported_names = sorted(set(mod.imported_names))
    mod.constants = sorted(set(mod.constants))
    mod.local_imports = sorted(set(mod.local_imports) - {rel})
    mod.functions = sorted(set(mod.functions), key=mod.functions.index)
    return mod, bits


def _flag(bits: RepoBits, node: ast.Call) -> None:
    flags = [str(_const(a)) for a in node.args if str(_const(a)).startswith("-")]
    kw = {k.arg: k.value for k in node.keywords if k.arg}
    choices: list[str] | None = None
    raw = kw.get("choices")
    typ = kw.get("type")
    if raw is None and isinstance(typ, ast.Call) and getattr(typ.func, "attr", "") == "Choice":
        raw = typ.args[0] if typ.args else None
    if isinstance(raw, ast.List | ast.Tuple):
        choices = [str(_const(e)) for e in raw.elts]
    for flag in flags:
        bits.cli[flag] = choices
    req = kw.get("required")
    if isinstance(req, ast.Constant) and req.value is True and flags:
        bits.required.append(flags[-1])
    if "--port" in flags and (port := _port(_int(kw.get("default")))) is not None:
        bits.ports.append(port)


def _settings_env(node: ast.ClassDef, bits: RepoBits) -> None:
    """pydantic ``BaseSettings`` fields are environment variables: ``env_prefix`` + the field name, upper case."""
    if not any("BaseSettings" in ast.unparse(b) for b in node.bases):
        return
    prefix = ""
    for sub in ast.walk(node):
        if isinstance(sub, ast.keyword) and sub.arg == "env_prefix" and isinstance(_const(sub.value), str):
            prefix = str(_const(sub.value))
        elif isinstance(sub, ast.Assign) and any(getattr(t, "id", "") == "env_prefix" for t in sub.targets):
            prefix = str(_const(sub.value) or "")
    for sub in node.body:
        if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name) and not sub.target.id.startswith("_") \
                and sub.target.id != "model_config":
            default = _const(sub.value) if sub.value is not None else None
            bits.env.setdefault((prefix + sub.target.id).upper(), None if default is None else str(default))


def _resolve_relative(module: str, name: str | None, level: int, rel: str) -> str:
    if level == 0:
        return name or ""
    parts = module.split(".")
    is_pkg = rel.endswith("__init__.py")
    base = parts if is_pkg else parts[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, *([name] if name else [])])


def _local(mod: ModuleFacts, dotted: str, local_names: dict[str, str]) -> bool:
    path = local_names.get(dotted)
    if path:
        mod.local_imports.append(path)
        return True
    return False


def module_name(rel: str, packages: set[str]) -> str:
    """Dotted name of a file: the path from the nearest folder that is not a package (has no ``__init__.py``)."""
    parts = rel.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    start = len(parts) - 1
    while start > 0 and "/".join(rel.split("/")[:start]) in packages:
        start -= 1
    return ".".join(parts[start:]) or rel
